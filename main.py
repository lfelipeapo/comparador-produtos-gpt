import jwt
import os
import backoff
import asyncio
import httpx
import json
import html
import re
import random
import time
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
from openai import OpenAI

# Configurar o cliente OpenAI com a chave correta
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ASSISTANT_ID = os.environ.get('ASSISTANT_ID')
ASSISTANT_ID_GROUP = os.environ.get('ASSISTANT_ID_GROUP')
SEARXNG_ENDPOINTS = [
    "https://smoggy-yasmeen-lfelipeapo-97ab6e01.koyeb.app/",
    "https://pesquisa-mt-q7m2taf0ob.koyeb.app/",
    # "https://meutudo-search-u69koy43zgt5zonu.onrender.com",
    # "https://mt-pesquisa-2uw5m7edjspsu5xh.onrender.com",
    # "https://search-mt-w5r6poyq8ojutb2w.onrender.com",
]
SECRET_KEY = os.getenv('SECRET_KEY')
ALLOWED_IPS = os.getenv('ALLOWED_IPS', '').split(',')
ALLOWED_DOMAINS = os.getenv('ALLOWED_DOMAINS', '').split(',')

app = FastAPI()

# Variáveis globais para armazenar o token e sua expiração
global_token = {
    "token": None,
    "expires_at": 0
}

import random

def generate_random_headers():
    user_agents = [
        # Lista de diferentes User-Agent strings
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/58.0.3029.110 Safari/537.3",

        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:55.0) "
        "Gecko/20100101 Firefox/55.0",

        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/11.1 Safari/605.1.15",

        "Mozilla/5.0 (iPhone; CPU iPhone OS 11_0 like Mac OS X) "
        "AppleWebKit/604.1.38 (KHTML, like Gecko) "
        "Version/11.0 Mobile/15A372 Safari/604.1",

        "Mozilla/5.0 (Linux; Android 8.0.0; SM-G950F) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/61.0.3163.98 Mobile Safari/537.36",

        # Novos User-Agents adicionados
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/90.0.4430.212 Safari/537.36",

        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/14.0.3 Safari/605.1.15",

        "Mozilla/5.0 (iPad; CPU OS 14_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/14.0 Mobile/15A5341f Safari/604.1",

        "Mozilla/5.0 (Linux; Android 11; SM-G991B) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/89.0.4389.105 Mobile Safari/537.36",

        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Edge/18.18363",

        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/88.0.4324.96 Safari/537.36",

        "Mozilla/5.0 (Macintosh; Intel Mac OS X 11_2_3) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/89.0.4389.114 Safari/537.36",

        "Mozilla/5.0 (iPhone; CPU iPhone OS 14_4 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/14.0 Mobile/15E148 Safari/604.1",

        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36",

        "Mozilla/5.0 (Linux; Android 9; Pixel 3 XL) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/78.0.3904.108 Mobile Safari/537.36",

        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/13.1.2 Safari/605.1.15",

        "Mozilla/5.0 (Windows NT 6.1; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/85.0.4183.102 Safari/537.36",

        "Mozilla/5.0 (iPad; CPU OS 13_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/13.1.2 Mobile/15E148 Safari/604.1"
        
        # Adicionar mais User-Agents se necessário
    ]

    headers = {
        "User-Agent": random.choice(user_agents),
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive"
    }

    return headers

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
    response = JSONResponse(content={'message': 'Token gerado com sucesso!'})
    response.headers['Authorization'] = f'Bearer {token}'
    return response

class JWTMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Ignorar validação para a rota /generate_token
        if request.url.path == "/generate_token":
            return await call_next(request)

        # Verificação do token JWT
        token = request.headers.get('Authorization')
        
        if token and token.startswith("Bearer "):
            token = token.split(" ")[1]
        
        if not token:
            raise HTTPException(status_code=403, detail='Token é necessário!')

        try:
            jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=403, detail='Token expirado!')
        except jwt.InvalidTokenError as e:
            print(f"Erro de token JWT: {e}")
            raise HTTPException(status_code=403, detail='Token inválido!')

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

client_openai = OpenAI(api_key=OPENAI_API_KEY)

class ProductRequest(BaseModel):
    product_name: str

@backoff.on_exception(backoff.expo, httpx.RequestError, max_tries=3)
async def get_token():
    current_time = time.time()
    if global_token["token"] and global_token["expires_at"] > current_time:
        return global_token["token"]

    endpoint = SEARXNG_ENDPOINTS[0]  # Seleciona o primeiro endpoint para gerar o token
    try:
        async with httpx.AsyncClient() as client_http:
            response = await client_http.post(f"{endpoint}/generate_token")
            if response.status_code == 200 and "Authorization" in response.headers:
                token = response.headers["Authorization"]
                global_token["token"] = token
                global_token["expires_at"] = current_time + 3600  # Token válido por 1 hora
                return token
            else:
                print(f"Erro ao obter token de {endpoint}: {response.status_code}")
                raise HTTPException(status_code=503, detail="Erro ao obter token de autenticação")
    except httpx.RequestError as e:
        print(f"Erro ao conectar ao endpoint {endpoint} para token: {e}")
        raise HTTPException(status_code=503, detail="Erro ao obter token de autenticação")

@backoff.on_exception(backoff.expo, httpx.RequestError, max_tries=3)
@backoff.on_exception(backoff.expo, httpx.RequestError, max_tries=3)
async def load_balancer_request(params, headers, timeout=30):
    for endpoint in SEARXNG_ENDPOINTS:
        try:
            async with httpx.AsyncClient() as client_http:
                response = await client_http.post(
                    f"{endpoint}/search",
                    params=params,
                    headers=headers,
                    timeout=timeout
                )
                if response.status_code == 200:
                    return response
                else:
                    print(f"Falha no endpoint {endpoint}: {response.status_code}")
                    print(f"Resposta: {response.text}")
        except httpx.RequestError as e:
            print(f"Erro ao conectar ao endpoint {endpoint}: {e}")
            continue  # Tenta o próximo endpoint

    raise HTTPException(status_code=503, detail="Todos os endpoints falharam.")
    
def send_products_to_api(products, assistant_id):
    thread = client_openai.beta.threads.create()

    message = client_openai.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=json.dumps(products)  # Envia como JSON string
    )

    run = client_openai.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant_id
    )

    timeout = 30
    start_time = time.time()
    while run.status != "completed":
        run = client_openai.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id
        )
        time.sleep(0.5)
        if time.time() - start_time > timeout:
            raise HTTPException(status_code=500, detail="Timeout ao executar o thread")

    messages = client_openai.beta.threads.messages.list(
        thread_id=thread.id
    )

    result = None
    for message in messages:
        for content in message.content:
            if content.text:
                result = content.text.value
                break
        if result:
            break

    return result

def validate_and_sanitize_product_name(product_name: str):
    if len(product_name.strip()) == 0:
        raise HTTPException(status_code=400, detail="Nome de produto não informado.")

    if len(product_name) > 50:
        raise HTTPException(status_code=400, detail="Nome do produto excede o tamanho permitido.")

    product_name = html.escape(product_name)

    # Ajuste na regex para permitir caracteres acentuados
    if not re.match(r"^[a-zA-Z0-9 _\-çãáàêéèíìõóòúùâôõ]+$", product_name):
        raise HTTPException(status_code=400, detail="Nome do produto contém caracteres inválidos.")

    sql_keywords = ["SELECT", "DROP", "INSERT", "DELETE", "UNION", "--", ";"]

    for keyword in sql_keywords:
        if re.search(rf"\b{keyword}\b", product_name, re.IGNORECASE):
            raise HTTPException(status_code=400, detail="Nome do produto contém termos suspeitos.")

    return product_name

@app.post("/search_products_by_type/")
async def search_products_by_type_endpoint():
    # Lista de tipos de produtos (mantida sem alterações)
    product_types = [
        "geladeira",
        "fogão",
        "micro-ondas",
        "lava-louças",
        "máquina de lavar roupa",
        "secadora de roupas",
        "aspirador de pó",
        "air fryer",
        "cafeteira",
        "torradeira",
        "liquidificador",
        "batedeira",
        "ferro de passar",
        "purificador de água",
        "ar-condicionado",
        "ventilador",
        "aquecedor",
        "panela elétrica",
        "grill elétrico",
        "forno elétrico",
        "sanduicheira",
        "fritadeira elétrica",
        "processador de alimentos",
        "coifa",
        "exaustor",
        "máquina de gelo",
        "adega climatizada",
        "máquina de costura",
        "lavadora de alta pressão",
        "cortador de grama",
        "triturador de alimentos",
        "fogão cooktop",
        "forno a gás",
        "bebedouro",
        "desumidificador",
        "umidificador",
        "aspirador robô",
        "chaleira elétrica",
        "espremedor de frutas",
        "sorveteira",
        "panela de arroz",
        "panela de pressão elétrica",
        "máquina de pão",
        "mopa a vapor",
        "purificador de ar",
        "cervejeira",
        "massageador",
        "máquina de crepe",
        "máquina de waffles",
        "forno elétrico de embutir",
        "sofá",
        "cama",
        "mesa de jantar",
        "cadeira",
        "guarda-roupa",
        "escrivaninha",
        "estante",
        "rack para TV",
        "mesa de centro",
        "poltrona",
        "colchão",
        "criado-mudo",
        "aparador",
        "penteadeira",
        "banqueta",
        "beliche",
        "painel para TV",
        "cabeceira",
        "cômoda",
        "mesa de escritório",
        "estante de livros",
        "sapateira",
        "buffet",
        "cristaleira",
        "divã",
        "camiseta",
        "calça jeans",
        "tênis",
        "bota",
        "bolsa",
        "relógio",
        "óculos de sol",
        "vestido",
        "saia",
        "camisa social",
        "jaqueta",
        "moletom",
        "blazer",
        "gravata",
        "brincos",
        "colar",
        "pulseira",
        "meia",
        "cueca",
        "sutiã",
        "boné",
        "chinelo",
        "cinto",
        "luvas",
        "cachecol",
        "perfume",
        "maquiagem",
        "shampoo",
        "condicionador",
        "creme hidratante",
        "protetor solar",
        "escova de dentes elétrica",
        "secador de cabelo",
        "chapinha",
        "barbeador elétrico",
        "aparador de pelos",
        "esfoliante",
        "sabonete líquido",
        "máscara facial",
        "kit manicure",
        "depilador elétrico",
        "lixa elétrica",
        "hidratante corporal",
        "kit de pincéis de maquiagem",
        "pinça",
        "creme anti-idade",
        "serum facial",
        "loção pós-barba",
        "tônico facial",
        "base para maquiagem",
        "bicicleta",
        "esteira",
        "roupas de ginástica",
        "halteres",
        "tênis de corrida",
        "bola de futebol",
        "skate",
        "patins",
        "suplementos alimentares",
        "tapete de yoga",
        "bicicleta ergométrica",
        "elíptico",
        "luvas de boxe",
        "barras de flexão",
        "corda de pular",
        "banco de musculação",
        "faixas elásticas",
        "step",
        "bola de pilates",
        "kettlebell",
        "roupas de natação",
        "mochila de hidratação",
        "gorro de natação",
        "óculos de natação",
        "acessórios para bicicleta",
        "smartphone",
        "notebook",
        "tablet",
        "smart TV",
        "headphone",
        "smartwatch",
        "câmera digital",
        "console de videogame",
        "caixa de som Bluetooth",
        "home theater",
        "projetor",
        "fone de ouvido sem fio",
        "monitor",
        "disco rígido externo",
        "impressora",
        "roteador",
        "mouse gamer",
        "teclado",
        "headset gamer",
        "placa de vídeo",
        "memória RAM",
        "SSD",
        "HD interno",
        "microfone",
        "leitor de e-book",
        "controle remoto universal",
        "antena digital",
        "estabilizador",
        "nobreak",
        "câmera de segurança",
        "drone",
        "power bank",
        "Chromecast",
        "Apple TV",
        "pen drive",
        "carregador de celular",
        "cabo HDMI",
        "suporte para TV",
        "adaptador USB",
        "carregador sem fio",
        "câmera instantânea",
        "fone com cancelamento de ruído",
        "placa-mãe",
        "processador",
        "kit de ferramentas eletrônicas",
        "leitor de cartão de memória",
        "lente para câmera",
        "flash para câmera",
        "livros",
        "DVDs",
        "blu-rays",
        "e-books",
        "CDs de música",
        "revistas",
        "áudiolivros",
        "quadrinhos",
        "mangás",
        "box de séries",
        "box de filmes",
        "enciclopédias",
        "mapas",
        "calendários",
        "agendas",
        "boneca",
        "carrinho de controle remoto",
        "quebra-cabeça",
        "Lego",
        "jogos de tabuleiro",
        "videogames",
        "bonecos de ação",
        "pelúcia",
        "drones infantis",
        "massinha de modelar",
        "brinquedos educativos",
        "blocos de montar",
        "patinete",
        "triciclo",
        "piscina de bolinhas",
        "casa de bonecas",
        "carrinho de bebê de brinquedo",
        "instrumentos musicais infantis",
        "jogo de dardos",
        "pista de carrinhos",
        "castelo inflável",
        "bolas esportivas",
        "fantasias",
        "jogos de cartas",
        "kit de mágica",
        "pneus",
        "GPS automotivo",
        "som automotivo",
        "suporte veicular para celular",
        "capa de volante",
        "tapetes para carro",
        "câmera de ré",
        "kit de primeiros socorros para carro",
        "carregador veicular",
        "aspirador de pó automotivo",
        "ração para pets",
        "coleira",
        "casinha para pets",
        "brinquedos para pets",
        "caixa de transporte",
        "arranhador",
        "comedouro automático",
        "aquário",
        "areia higiênica",
        "bebedouro para pets"
    ]

    categorias = {}

    for product_type in product_types:
        sanitized_type = validate_and_sanitize_product_name(product_type)
        print(f"Processando tipo de produto: {sanitized_type}")

        data = {
            "q": sanitized_type,
            "format": "json",
            # "engines": "buscape,zoom"
        }
        token = await get_token()
        headers = generate_random_headers()
        headers["Authorization"] = token

        try:
            search_response = await load_balancer_request(data, headers)
            search_results = search_response.json()

            if not search_results or 'results' not in search_results:
                print(f"Erro: Resposta de pesquisa inválida para o tipo {sanitized_type}.")
                categorias[product_type] = {"error": "Resposta inválida do serviço de pesquisa."}
                continue

            # Enviar o JSON completo ao GPT
            resultado_assistente = send_products_to_api(search_results, ASSISTANT_ID_GROUP)
            print(f"Resposta do assistente para {product_type}: {resultado_assistente}")

            # Converter a resposta do GPT para JSON
            try:
                resultado_assistente = json.loads(resultado_assistente) if isinstance(resultado_assistente, str) else resultado_assistente
                if not isinstance(resultado_assistente, dict):
                    raise ValueError("Formato da resposta inesperado")
            except json.JSONDecodeError:
                categorias[product_type] = {"error": "Resposta do assistente não é um JSON válido."}
                continue

            if resultado_assistente.get('erro') == True and resultado_assistente.get('mensagemErro') == "Nenhum produto válido encontrado ou entrada inválida.":
                print(f"Erro detectado para {product_type}: {resultado_assistente['mensagemErro']}. Tentando outro endpoint.")
                # Remove o endpoint atual dos disponíveis e tenta novamente
                current_endpoint = SEARXNG_ENDPOINTS[0]
                SEARXNG_ENDPOINTS.pop(0)

                if not SEARXNG_ENDPOINTS:
                    categorias[product_type] = {"error": "Nenhum endpoint disponível para processar a solicitação."}
                    continue

                # Tenta novamente com o próximo endpoint
                token = await get_token()
                headers = generate_random_headers()
                headers["Authorization"] = token
                search_response = await load_balancer_request(data, headers)
                search_results = search_response.json()

                if not search_results or 'results' not in search_results:
                    print(f"Erro: Resposta de pesquisa inválida para o tipo {sanitized_type} após tentar outro endpoint.")
                    categorias[product_type] = {"error": "Resposta inválida do serviço de pesquisa após tentar outro endpoint."}
                    continue

                resultado_assistente = send_products_to_api(search_results, ASSISTANT_ID_GROUP)
                print(f"Resposta do assistente para {product_type} após tentar outro endpoint: {resultado_assistente}")

                try:
                    resultado_assistente = json.loads(resultado_assistente) if isinstance(resultado_assistente, str) else resultado_assistente
                    if not isinstance(resultado_assistente, dict):
                        raise ValueError("Formato da resposta inesperado após tentar outro endpoint")
                except json.JSONDecodeError:
                    categorias[product_type] = {"error": "Resposta do assistente não é um JSON válido após tentar outro endpoint."}
                    continue

                categorias[product_type] = resultado_assistente.get('categorias', {})
            else:
                categorias[product_type] = resultado_assistente.get('categorias', {})

        except HTTPException as he:
            categorias[product_type] = {"error": he.detail}
        except ValueError as ve:
            categorias[product_type] = {"error": "Formato da resposta do assistente é inesperado."}
        except Exception as e:
            categorias[product_type] = {"error": f"Erro ao processar: {e}"}

    resultado_final = {
        "categorias": categorias,
        "dataConsulta": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "erro": False,
        "mensagemErro": None
    }

    return resultado_final
    
@app.post("/search_product/")
async def search_product(request: ProductRequest):
    # Extrair o nome do produto do corpo da requisição
    product_name = request.product_name
    print(f"Recebendo requisição para produto: {product_name}")
    
    # Validar e sanitizar o nome do produto
    product_name = validate_and_sanitize_product_name(product_name)
    print(f"Produto sanitizado: {product_name}")

    data = {
        "q": product_name,
        "format": "json",
        # "engines": "buscape,zoom"
    }
    token = await get_token()
    headers = generate_random_headers()
    headers["Authorization"] = token

    try:
        search_response = await load_balancer_request(data, headers)
        # Log do status e conteúdo da resposta
        print(f"Status Code: {search_response.status_code}")
        print(f"Response Content: {search_response.text}")

        if search_response.status_code != 200:
            raise HTTPException(status_code=503, detail="Serviço de pesquisa retornou um erro.")

        search_results = search_response.json()
    except httpx.RequestError as e:
        print(f"Erro ao conectar ao serviço de pesquisa: {e}")
        raise HTTPException(status_code=503, detail="Não foi possível conectar ao serviço de pesquisa.")
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Resposta do serviço de pesquisa não é um JSON válido.")
    except Exception as e:
        print(f"Erro inesperado: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor.")

    if not search_results or not isinstance(search_results, dict) or 'results' not in search_results:
        print("Erro: Resposta de pesquisa inválida ou inesperada.")
        raise HTTPException(status_code=500, detail="Resposta inválida: campo 'results' ausente.")

    try:
        resultado_assistente = send_products_to_api(search_results, ASSISTANT_ID_GROUP)
        print(f"Resposta do assistente: {resultado_assistente}")

        # Converter a resposta do assistente para JSON
        try:
            resultado_assistente = json.loads(resultado_assistente) if isinstance(resultado_assistente, str) else resultado_assistente
            if not isinstance(resultado_assistente, dict):
                raise ValueError("Formato da resposta inesperado")
        except json.JSONDecodeError:
            raise ValueError("Resposta do assistente não é um JSON válido")

        if resultado_assistente.get('erro') == True and resultado_assistente.get('mensagemErro') == "Nenhum produto válido encontrado ou entrada inválida.":
            print(f"Erro detectado para {product_name}: {resultado_assistente['mensagemErro']}. Tentando outro endpoint.")
            # Remove o endpoint atual dos disponíveis e tenta novamente
            current_endpoint = SEARXNG_ENDPOINTS[0]
            SEARXNG_ENDPOINTS.pop(0)

            if not SEARXNG_ENDPOINTS:
                return {"erro": True, "mensagemErro": "Nenhum endpoint disponível para processar a solicitação."}

            # Tenta novamente com o próximo endpoint
            token = await get_token()
            headers = generate_random_headers()
            headers["Authorization"] = token
            search_response = await load_balancer_request(data, headers)
            search_results = search_response.json()

            if not search_results or 'results' not in search_results:
                print(f"Erro: Resposta de pesquisa inválida para o produto {product_name} após tentar outro endpoint.")
                return {"erro": True, "mensagemErro": "Resposta inválida do serviço de pesquisa após tentar outro endpoint."}

            resultado_assistente = send_products_to_api(search_results, ASSISTANT_ID_GROUP)
            print(f"Resposta do assistente para {product_name} após tentar outro endpoint: {resultado_assistente}")

            try:
                resultado_assistente = json.loads(resultado_assistente) if isinstance(resultado_assistente, str) else resultado_assistente
                if not isinstance(resultado_assistente, dict):
                    raise ValueError("Formato da resposta inesperado após tentar outro endpoint")
            except json.JSONDecodeError:
                return {"erro": True, "mensagemErro": "Resposta do assistente não é um JSON válido após tentar outro endpoint."}

            return resultado_assistente
        else:
            return resultado_assistente

    except HTTPException as he:
        return {"erro": True, "mensagemErro": he.detail}
    except ValueError as ve:
        print(f"Erro de formato na resposta do assistente: {ve}")
        return {"erro": True, "mensagemErro": "Formato da resposta do assistente é inesperado."}
    except Exception as e:
        print(f"Erro ao processar a resposta do assistente: {e}")
        return {"erro": True, "mensagemErro": f"Erro ao processar a resposta do assistente: {e}"}

# Endpoint de saúde para verificação rápida
@app.get("/health")
async def health_check():
    return {"status": "OK"}
