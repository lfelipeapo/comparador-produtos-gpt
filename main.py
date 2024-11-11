import jwt
import os
import backoff
import asyncio
import httpx
import json
import html
import re
import time
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
from openai import OpenAI
from typing import Any
from unidecode import unidecode

# Configurar o cliente OpenAI com a chave correta
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ASSISTANT_ID = os.environ.get('ASSISTANT_ID')
ASSISTANT_ID_GROUP = os.environ.get('ASSISTANT_ID_GROUP')
SEARXNG_ENDPOINTS = [
    "https://smoggy-yasmeen-lfelipeapo-97ab6e01.koyeb.app/",
    "https://pesquisa-mt-q7m2taf0ob.koyeb.app/",
    "https://marine-cougar-lipe-7c0433f9.koyeb.app/"
]
SECRET_KEY = os.getenv('SECRET_KEY')
ALLOWED_IPS = ["179.145.62.197", "177.96.21.178", "179.87.199.45", "100.20.92.101", "44.225.181.72", "44.227.217.144"]
ALLOWED_DOMAINS = ["meutudo.com.br", "deploymenttest.meutudo.com.br"]

app = FastAPI()

class CustomJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False).encode("utf-8")

def verificar_e_renovar_token(token: str) -> str:
    try:
        tempo_atual = time.time()
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        
        # Verifica se o token já expirou ou está prestes a expirar
        if payload['exp'] <= tempo_atual or payload['exp'] - tempo_atual < 300:
            # Gera um novo token
            novo_payload = {
                'ip': payload['ip'],
                'domain': payload['domain'],
                'exp': tempo_atual + 3600  # Novo token válido por 1 hora
            }
            novo_token = jwt.encode(novo_payload, SECRET_KEY, algorithm='HS256')
            return f"Bearer {novo_token}"
        
        # Se o token ainda é válido e não está próximo de expirar, retorna o mesmo token
        return f"Bearer {token}"
    except jwt.ExpiredSignatureError:
        # Se não foi possível decodificar o token porque já expirou, tenta renovar
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"], options={"verify_exp": False})
            novo_payload = {
                'ip': payload['ip'],
                'domain': payload['domain'],
                'exp': time.time() + 3600  # Novo token válido por 1 hora
            }
            novo_token = jwt.encode(novo_payload, SECRET_KEY, algorithm='HS256')
            return f"Bearer {novo_token}"
        except:
            # Se não for possível renovar, então lançamos uma exceção
            raise HTTPException(status_code=403, detail='Token expirado e não pode ser renovado. Por favor, gere um novo token.')
    except jwt.InvalidTokenError as e:
        print(f"Erro de token JWT: {e}")
        raise HTTPException(status_code=403, detail='Token inválido!')

@app.post("/generate_token")
async def generate_token(request: Request):
    # Validação de IP e Domínio
    client_ip = request.client.host
    referer = request.headers.get('Referer')
    domain = referer.split('/')[2] if referer and len(referer.split('/')) > 2 else None

    # Se o IP ou o Domínio estiver permitido, passa. Caso contrário, bloqueia.
    if client_ip not in ALLOWED_IPS and (domain is None or domain not in ALLOWED_DOMAINS):
        raise HTTPException(status_code=403, detail='Acesso negado: IP ou Domínio não autorizado!')

    # Dados para o token JWT
    payload = {
        'ip': client_ip,
        'domain': domain,
        'exp': time.time() + 3600  # Token expira em 1 hora
    }

    # Geração do token JWT
    token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')

    # Retornar o token no header da resposta
    response = CustomJSONResponse(content={'message': 'Token gerado com sucesso!'})
    response.headers['Authorization'] = f'Bearer {token}'
    return response

class JWTMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/generate_token":
            return await call_next(request)

        token = request.headers.get('Authorization')
        if token and token.startswith("Bearer "):
            token = token.split(" ")[1]
        
        if not token:
            raise HTTPException(status_code=403, detail='Token é necessário!')

        try:
            novo_token = verificar_e_renovar_token(token)
            request.state.token = novo_token
            response = await call_next(request)
            response.headers['Authorization'] = novo_token
            return response
        except HTTPException as e:
            return CustomJSONResponse(status_code=e.status_code, content={"detail": e.detail})
            
        # Validação de IP e Domínio
        client_ip = request.client.host
        referer = request.headers.get('Referer')
        domain = referer.split('/')[2] if referer and len(referer.split('/')) > 2 else None
        
        # Se o IP ou o Domínio estiver permitido, passa. Caso contrário, bloqueia.
        if client_ip not in ALLOWED_IPS and (domain is None or domain not in ALLOWED_DOMAINS):
            raise HTTPException(status_code=403, detail='Acesso negado: IP ou Domínio não autorizado!')

        response = await call_next(request)
        return response

# Adiciona o middleware à aplicação
app.add_middleware(JWTMiddleware)

# Verifique se as variáveis de ambiente estão definidas
missing_vars = []
for var in ['OPENAI_API_KEY', 'ASSISTANT_ID', 'ASSISTANT_ID_GROUP']:
    if not os.environ.get(var):
        missing_vars.append(var)
if missing_vars:
    raise ValueError(f"As seguintes variáveis de ambiente não estão definidas: {', '.join(missing_vars)}")

client = OpenAI(api_key=OPENAI_API_KEY)

class ProductRequest(BaseModel):
    product_name: str

@backoff.on_exception(backoff.expo, httpx.RequestError, max_tries=3)
async def get_token_from_endpoint(endpoint):
    try:
        async with httpx.AsyncClient() as client_http:
            response = await client_http.post(f"{endpoint}/generate_token")
            if response.status_code == 200 and "Authorization" in response.headers:
                token = response.headers["Authorization"]
                return token
            else:
                print(f"Erro ao obter token de {endpoint}: {response.status_code}")
                raise HTTPException(status_code=503, detail="Erro ao obter token de autenticação")
    except httpx.RequestError as e:
        print(f"Erro ao conectar ao endpoint {endpoint} para token: {e}")
        raise HTTPException(status_code=503, detail="Erro ao obter token de autenticação")

import random

def should_continue_trying(response):
    if 'error' in response and response['error'] and 'code' in response['error'] and response['error']['code'] == 'false':
        return False
    if 'results' in response and response['results'] and len(response['results']) > 0:
        return False
    return True

@backoff.on_exception(backoff.expo, httpx.RequestError, max_tries=3)
async def load_balancer_request(data, headers, timeout=60, max_attempts=3):
    endpoints = SEARXNG_ENDPOINTS[:]  # Cria uma cópia da lista de endpoints
    for _ in range(max_attempts):
        random.shuffle(endpoints)  # Embaralha a lista de endpoints para randomizar a ordem
        for endpoint in endpoints:
            try:
                # Delay aleatorio
                await asyncio.sleep(random.uniform(0.5, 2.0))
                # Obter o token antes de fazer a requisição
                token = await get_token_from_endpoint(endpoint)
                headers["Authorization"] = token
                async with httpx.AsyncClient() as client_http:
                    response = await client_http.post(
                        f"{endpoint}/search", data=data, headers=headers, timeout=timeout
                    )
                    if response.status_code == 200:
                        search_response = response.json()
                        if not should_continue_trying(search_response):  # Verifica se deve continuar ou não
                            # Verificar se o token foi renovado
                            novo_token = response.headers.get('Authorization')
                            if novo_token:
                                headers["Authorization"] = novo_token
                            return search_response
            except httpx.RequestError as e:
                print(f"Erro ao conectar ao endpoint {endpoint}: {e}")
        # Se todos os endpoints falharem, pode escolher continuar ou parar
    raise HTTPException(status_code=503, detail="Todos os endpoints falharam.")

def verifica_engines_nao_responsivas(search_response):
    unresponsive = search_response.get('unresponsive_engines', [])
    motores_suspensos = []

    for motor, mensagem in unresponsive:
        if 'acesso negado' or 'tempo esgotado' in mensagem.lower():
            motores_suspensos.append(motor)
    
    # Verifica se ambos os motores 'buscape' e 'zoom' estão suspensos
    if 'buscape' in motores_suspensos and 'zoom' in motores_suspensos:
        return ['buscape', 'zoom']
    
    return motores_suspensos

def gerar_prompt_alternativo(product_name):
    sites = " OR ".join([
        "site:google.com/shopping",
        "site:mercadolivre.com.br",
        "site:buscape.com.br",
        "site:zoom.com.br",
        "site:magazineluiza.com.br",
        "site:casasbahia.com.br",
        "site:americanas.com.br",
        "site:amazon.com.br",
        "site:shoptime.com.br",
        "site:polishop.com.br",
        "site:koerich.com.br",
        "site:kabum.com.br",
        "site:extra.com.br",
        "site:pontofrio.com.br",
        "site:berlanda.com.br",
        "site:lojasmm.com",
        "site:continentalbrasil.com.br",
        "site:loja.electrolux.com.br",
        "site:consul.com.br",
        "site:brastemp.com.br",
        "site:havan.com.br",
        "site:compracerta.com.br",
        "site:madeiramadeira.com.br",
        "site:pernambucanas.com.br",
        "site:colombo.com.br",
        "site:ricardoeletro.com.br",
        "site:riachuelo.com.br",
        "site:marisa.com.br",
        "site:lojasrenner.com.br",
        "site:posthaus.com.br",
        "site:arezzo.com.br",
        "site:cea.com.br",
        "site:vestcasa.com.br",
        "site:wtennis.com.br",
        "site:milium.com.br",
        "site:lebiscuit.com.br",
        "site:benoit.com.br",
        "site:lojasemporio.com.br",
        "site:samsung.com/br"
        "site:dell.com/pt-br",
        "site:zattini.com.br",
        "site:dafiti.com.br",
        "site:netshoes.com.br",
        "site:natura.com.br",
        "site:cacaushow.com.br"
        "site:boticario.com.br",
        "site:tupperware.com.br"
        "site:brasilcacau.com.br",
        "site:motorola.com.br",
        "site:adidas.com.br",
        "site:vivara.com.br"
    ])
    
    # Retorna o prompt formatado
    return fr"{product_name} $ +R$ +preco ({sites}) -inurl:blog -inurl:promocao -melhores -melhor -/busca -/blog -lista."
    
def send_products_to_api(products, assistant_id):
    try:
        # Criar o thread
        thread = client.beta.threads.create()

        # Adicionar mensagens ao thread
        message = client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=f"{products}"
        )

        # Executar o thread com o assistente v2
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant_id
        )

        # Verificar o status do run até ser concluído
        timeout = 60
        start_time = time.time()
        while run.status != "completed":
            run = client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id
            )
            time.sleep(0.5)
            if time.time() - start_time > timeout:
                raise HTTPException(status_code=500, detail="Timeout ao executar o thread")

        # Recuperar as mensagens do thread após o run ser completado
        messages = client.beta.threads.messages.list(
            thread_id=thread.id
        )

        # Extrair as informações da resposta do OpenAI
        result = None
        for message in messages:
            for content in message.content:
                if content.text:
                    result = content.text.value
                    break
            if result:
                break

        if not result:
            raise ValueError("Não foi possível extrair uma resposta válida do assistente")

        return result

    except HTTPException as he:
        # Repassar exceções HTTP
        raise he
    except Exception as e:
        # Logar o erro e levantar uma exceção HTTP genérica
        print(f"Erro ao processar produtos na API: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar a requisição: {str(e)}")

def validate_and_sanitize_product_name(product_name: str):
    # Validar se existe nome de produto
    if not isinstance(product_name, str) or len(product_name.strip()) == 0:
        raise HTTPException(status_code=400, detail="Nome de produto não informado.")

    # Limitar o tamanho do nome do produto para evitar ataques de buffer overflow
    if len(product_name) > 50:
        raise HTTPException(status_code=400, detail="Nome do produto excede o tamanho permitido.")

    # Sanitização básica contra XSS
    product_name = html.escape(product_name)

    # Expressão regular para permitir letras, números, espaço, hífen, sublinhado e caracteres acentuados
    if not re.match(r"^[a-zA-Z0-9 _-çáéíóúâêîôûãõàèìòùäëïöüñÇÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÄËÏÖÜÑ]+$", product_name):
        raise HTTPException(status_code=400, detail="Nome do produto contém caracteres inválidos.")

    # Prevenção contra SQL injection: restrição simplificada apenas para os termos críticos
    sql_keywords = ["SELECT", "DROP", "INSERT", "DELETE", "UNION", "--", ";"]

    for keyword in sql_keywords:
        if re.search(rf"\b{keyword}\b", product_name, re.IGNORECASE):
            raise HTTPException(status_code=400, detail="Nome do produto contém termos suspeitos.")

    # Substituir 'ç' por 'c'
    product_name = product_name.replace('ç', 'c').replace('Ç', 'C')

    # Remover acentos usando unidecode
    product_name = unidecode(product_name)

    return product_name

# Lista de User-Agents populares para variar entre as requisições
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Firefox/55.0 Safari/537.3",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.93 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile Safari/604.1"
]

# Função para gerar cabeçalhos dinâmicos
# Função para gerar cabeçalhos dinâmicos
def generate_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": random.choice(["en-US,en;q=0.5", "pt-BR,pt;q=0.9,en;q=0.8"]),
        "Accept-Charset": random.choice(["utf-8", "ISO-8859-1"]),
        "Connection": random.choice(["keep-alive", "close"]),
        "Referer": "https://meutudo.com.br"
    }

@app.post("/search_product/", response_class=CustomJSONResponse)
async def search_product(request: ProductRequest):
    try:
        # Extrair e sanitizar o nome do produto
        product_name = validate_and_sanitize_product_name(request.product_name)
        print(f"[LOG] Produto recebido para busca: {product_name}")
        
        data = {
            "q": product_name,
            "format": "json",
            "engines": "buscape,zoom"
        }
        headers = generate_headers()
        
        # Faz a primeira tentativa com os motores principais
        search_response = await load_balancer_request(data, headers)
        print(f"[LOG] Resposta dos motores principais: Status {search_response.status_code}, Conteúdo: {search_response.text}")
        
        search_results = search_response.json()
        print(f"[LOG] Resultados da primeira tentativa: {search_results}")

        # Verifica motores suspensos e recorre ao alternativo se necessário
        motores_suspensos = verifica_engines_nao_responsivas(search_results)
        print(f"[LOG] Motores suspensos: {motores_suspensos}")

        if motores_suspensos == ['buscape', 'zoom']:
            print("[LOG] Motores 'buscape' e 'zoom' indisponíveis. Tentando com endpoint alternativo.")
            
            # Configura o prompt alternativo
            prompt_alternativo = gerar_prompt_alternativo(product_name)
            data_alternativo = {
                "q": prompt_alternativo,
                "format": "json",
            }

            # Loop para tentar o endpoint alternativo
            for tentativa in range(1, 4):  # Limita a 3 tentativas para evitar chamadas desnecessárias
                print(f"[LOG] Tentativa {tentativa} com endpoint alternativo para '{product_name}' com prompt: {prompt_alternativo}")
                search_response_alternativo = await load_balancer_request(data_alternativo, headers)
                
                # Loga o status e o conteúdo da resposta da tentativa com o alternativo
                print(f"[LOG] Resposta do endpoint alternativo: Status {search_response_alternativo.status_code}, Conteúdo: {search_response_alternativo.text}")
                
                if search_response_alternativo.status_code == 200:
                    search_results = search_response_alternativo.json()
                    print(f"[LOG] Resultados obtidos na tentativa {tentativa} do alternativo: {search_results}")
                    
                    # Se encontrou resultados válidos, interrompe o loop e processa a resposta
                    if search_results.get("results"):
                        print(f"[LOG] Resultado válido encontrado no endpoint alternativo na tentativa {tentativa}")
                        break
                    else:
                        print(f"[LOG] Nenhum resultado encontrado na tentativa {tentativa} do alternativo.")
                else:
                    print(f"[LOG] Falha no endpoint alternativo na tentativa {tentativa}. Tentando novamente...")

        # Envia os resultados processados para a API do assistente
        print(f"[LOG] Enviando resultados processados para a API do assistente. Dados: {search_results}")
        result = send_products_to_api(search_results, ASSISTANT_ID_GROUP)

        # Processa a resposta do assistente e retorna
        print(f"[LOG] Resposta do assistente recebida: {result}")
        if isinstance(result, str):
            result = json.loads(result)
        elif not isinstance(result, dict):
            raise ValueError("Formato da resposta inesperado")

        print("[LOG] Retornando resultados finais para o cliente.")
        return result

    except httpx.RequestError as e:
        print(f"[ERRO] Erro ao conectar ao serviço de pesquisa: {e}")
        raise HTTPException(status_code=503, detail="Não foi possível conectar ao serviço de pesquisa.")
    except json.JSONDecodeError as e:
        print(f"[ERRO] Erro ao decodificar JSON: {e}")
        raise HTTPException(status_code=500, detail="Resposta não é um JSON válido.")
    except ValueError as ve:
        print(f"[ERRO] Erro de valor: {ve}")
        raise HTTPException(status_code=500, detail=str(ve))
    except HTTPException as he:
        print(f"[ERRO] HTTPException: {he.detail}")
        raise he
    except Exception as e:
        print(f"[ERRO] Erro inesperado: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro interno do servidor: {str(e)}")

# Endpoint de saúde para verificação rápida
@app.get("/health")
async def health_check():
    return {"status": "OK"}
