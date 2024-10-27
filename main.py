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

# Configurar o cliente OpenAI com a chave correta
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ASSISTANT_ID = os.environ.get('ASSISTANT_ID')
ASSISTANT_ID_GROUP = os.environ.get('ASSISTANT_ID_GROUP')
SEARXNG_ENDPOINTS = [
    "https://smoggy-yasmeen-lfelipeapo-97ab6e01.koyeb.app/",
    "https://pesquisa-mt-q7m2taf0ob.koyeb.app/",
    "https://marine-cougar-lipe-7c0433f9.koyeb.app/",
    # "https://meutudo-search-u69koy43zgt5zonu.onrender.com",
    # "https://mt-pesquisa-2uw5m7edjspsu5xh.onrender.com",
    # "https://search-mt-w5r6poyq8ojutb2w.onrender.com",
]
SECRET_KEY = os.getenv('SECRET_KEY')
ALLOWED_IPS = ["179.145.62.197", "177.96.21.178", "179.87.199.45", "100.20.92.101", "44.225.181.72", "44.227.217.144"]
ALLOWED_DOMAINS = ["meutudo.com.br", "deploymenttest.meutudo.com.br"]

app = FastAPI()

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

@backoff.on_exception(backoff.expo, httpx.RequestError, max_tries=3)
async def load_balancer_request(data, headers, timeout=30):
    for endpoint in SEARXNG_ENDPOINTS:
        try:
            # Obter o token antes de fazer a requisição
            token = await get_token_from_endpoint(endpoint)
            headers["Authorization"] = token
            
            async with httpx.AsyncClient() as client_http:
                response = await client_http.post(
                    f"{endpoint}/search",
                    data=data,
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
    raise HTTPException(status_code=503, detail="Todos os endpoints falharam.")

def verifica_engines_nao_responsivas(search_response):
    unresponsive = search_response.get('unresponsive_engines', [])
    # Verifica se tanto 'buscape' quanto 'zoom' estão na mesma mensagem de erro
    motores_suspensos = []
    for motor, mensagem in unresponsive:
        if 'acesso negado' in mensagem.lower():
            motores_suspensos.append(motor)
    
    # Confirma se ambos os motores estão suspensos
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
    return fr"{product_name} +R$ +preco ({sites}) -inurl:blog -inurl:promocao -melhores -melhor -/busca -/blog -lista."
# Função para enviar a lista de produtos para a API
def send_products_to_api(products, assistant_id):
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
    timeout = 30
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

    # Retornar a última resposta do assistente
    return result

def validate_and_sanitize_product_name(product_name: str):
    # Validar se existe nome de produto
    if len(product_name.strip()) == 0:
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

    return product_name

# Endpoint de pesquisa de produtos
@app.post("/search_product/")
async def search_product(request: ProductRequest):
    # Extrair o nome do produto do corpo da requisição
    product_name = request.product_name
    print(f"Recebendo requisição para produto: {product_name}")
    
    # Validar e sanitizar o nome do produto
    product_name = validate_and_sanitize_product_name(product_name)
    print(f"Produto sanitizado: {product_name}")

    try:
        data = {
            "q": product_name,
            "format": "json",
            "engines": "buscape,zoom"
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/58.0.3029.110 Safari/537.3",
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive"
        }
        search_response = await load_balancer_request(data, headers)
        # Log do status e conteúdo da resposta
        print(f"Status Code: {search_response.status_code}")
        print(f"Response Content: {search_response.text}")

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

    # Verificação de motores não responsivos
    motores_suspensos = verifica_engines_nao_responsivas(search_results)

    if motores_suspensos == ['buscape', 'zoom']:
        print(f"Motores suspensos detectados: {motores_suspensos}")
        # Utiliza o prompt alternativo se os motores principais estiverem suspensos
        prompt_alternativo = gerar_prompt_alternativo(product_name)
        data_alternativo = {
            "q": prompt_alternativo,
            "format": "json",
        }
        try:
            search_response_alternativo = await load_balancer_request(data_alternativo, headers)
            print(f"Status Code (Alternativo): {search_response_alternativo.status_code}")
            print(f"Response Content (Alternativo): {search_response_alternativo.text}")

            if search_response_alternativo.status_code != 200:
                raise HTTPException(status_code=503, detail="Serviço de pesquisa alternativo retornou um erro.")

            search_results = search_response_alternativo.json()

            # Verificar se a busca alternativo retornou resultados
            if not search_results.get('results'):
                raise HTTPException(status_code=404, detail="Nenhum produto encontrado na busca alternativa.")
        except httpx.RequestError as e:
            print(f"Erro ao conectar ao serviço de pesquisa alternativo: {e}")
            raise HTTPException(status_code=503, detail="Não foi possível conectar ao serviço de pesquisa alternativo.")
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="Resposta do serviço de pesquisa alternativo não é um JSON válido.")
        except Exception as e:
            print(f"Erro inesperado na pesquisa alternativa: {e}")
            raise HTTPException(status_code=500, detail="Erro interno do servidor na pesquisa alternativa.")

    try:
        products = search_results.get('results')
        print(f"Produtos obtidos: {products}")
        if not products:
            raise HTTPException(status_code=404, detail="Nenhum produto encontrado.")
        result = send_products_to_api(products, ASSISTANT_ID_GROUP)
        print(f"Resposta do assistente: {result}")

        # Tente carregar o JSON diretamente da resposta
        if isinstance(result, str):
            result = json.loads(result)
        elif not isinstance(result, dict):
            raise ValueError("Formato da resposta inesperado")

        return result
    except json.JSONDecodeError as e:
        print(f"Erro ao converter a resposta do assistente para JSON: {e}")
        return {"error": "Resposta do assistente não é um JSON válido."}
    except ValueError as ve:
        print(f"Erro de formato na resposta do assistente: {ve}")
        return {"error": "Formato da resposta do assistente é inesperado."}
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Erro ao processar a resposta do assistente: {e}")
        return {"error": f"Erro ao processar a resposta do assistente: {e}"}

# # Função auxiliar para buscar produtos por tipo
# async def fetch_product_type(product_type):
#     try:
#         headers = {
#             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#                           "AppleWebKit/537.36 (KHTML, like Gecko) "
#                           "Chrome/58.0.3029.110 Safari/537.3",
#             "Accept": "application/json",
#             "Accept-Encoding": "gzip, deflate",
#             "Connection": "keep-alive"
#         }
#         data = {
#             "q": product_type,
#             "format": "json",
#             "engines": "buscape,zoom"
#         }
#         search_response = await load_balancer_request(data, headers)
#         # Verifica se o status da resposta é 200 (OK)
#         if search_response.status_code != 200:
#             return (product_type, {"error": "Falha na pesquisa."})
#         # Tenta fazer o parsing do JSON
#         search_results = search_response.json()
#         products = search_results.get('results', [])
#         return (product_type, products)
#     except httpx.RequestError as e:
#         print(f"Erro ao conectar ao serviço de pesquisa para o tipo {product_type}: {e}")
#         return (product_type, {"error": "Falha na pesquisa."})
#     except json.JSONDecodeError:
#         return (product_type, {"error": "Resposta do serviço de pesquisa não é um JSON válido."})
#     except Exception as e:
#         print(f"Erro inesperado ao buscar o tipo {product_type}: {e}")
#         return (product_type, {"error": "Falha na pesquisa."})
        
# # Função para pesquisar produtos por tipo
# async def search_products_by_type():
#     # Lista de tipos de produtos (mantida sem alterações)
#     product_types = [
#         "geladeira",
#         "fogão",
#         "micro-ondas",
#         "lava-louças",
#         "máquina de lavar roupa",
#         "secadora de roupas",
#         "aspirador de pó",
#         "air fryer",
#         "cafeteira",
#         "torradeira",
#         "liquidificador",
#         "batedeira",
#         "ferro de passar",
#         "purificador de água",
#         "ar-condicionado",
#         "ventilador",
#         "aquecedor",
#         "panela elétrica",
#         "grill elétrico",
#         "forno elétrico",
#         "sanduicheira",
#         "fritadeira elétrica",
#         "processador de alimentos",
#         "coifa",
#         "exaustor",
#         "máquina de gelo",
#         "adega climatizada",
#         "máquina de costura",
#         "lavadora de alta pressão",
#         "cortador de grama",
#         "triturador de alimentos",
#         "fogão cooktop",
#         "forno a gás",
#         "bebedouro",
#         "desumidificador",
#         "umidificador",
#         "aspirador robô",
#         "chaleira elétrica",
#         "espremedor de frutas",
#         "sorveteira",
#         "panela de arroz",
#         "panela de pressão elétrica",
#         "máquina de pão",
#         "mopa a vapor",
#         "purificador de ar",
#         "cervejeira",
#         "massageador",
#         "máquina de crepe",
#         "máquina de waffles",
#         "forno elétrico de embutir",
#         "sofá",
#         "cama",
#         "mesa de jantar",
#         "cadeira",
#         "guarda-roupa",
#         "escrivaninha",
#         "estante",
#         "rack para TV",
#         "mesa de centro",
#         "poltrona",
#         "colchão",
#         "criado-mudo",
#         "aparador",
#         "penteadeira",
#         "banqueta",
#         "beliche",
#         "painel para TV",
#         "cabeceira",
#         "cômoda",
#         "mesa de escritório",
#         "estante de livros",
#         "sapateira",
#         "buffet",
#         "cristaleira",
#         "divã",
#         "camiseta",
#         "calça jeans",
#         "tênis",
#         "bota",
#         "bolsa",
#         "relógio",
#         "óculos de sol",
#         "vestido",
#         "saia",
#         "camisa social",
#         "jaqueta",
#         "moletom",
#         "blazer",
#         "gravata",
#         "brincos",
#         "colar",
#         "pulseira",
#         "meia",
#         "cueca",
#         "sutiã",
#         "boné",
#         "chinelo",
#         "cinto",
#         "luvas",
#         "cachecol",
#         "perfume",
#         "maquiagem",
#         "shampoo",
#         "condicionador",
#         "creme hidratante",
#         "protetor solar",
#         "escova de dentes elétrica",
#         "secador de cabelo",
#         "chapinha",
#         "barbeador elétrico",
#         "aparador de pelos",
#         "esfoliante",
#         "sabonete líquido",
#         "máscara facial",
#         "kit manicure",
#         "depilador elétrico",
#         "lixa elétrica",
#         "hidratante corporal",
#         "kit de pincéis de maquiagem",
#         "pinça",
#         "creme anti-idade",
#         "serum facial",
#         "loção pós-barba",
#         "tônico facial",
#         "base para maquiagem",
#         "bicicleta",
#         "esteira",
#         "roupas de ginástica",
#         "halteres",
#         "tênis de corrida",
#         "bola de futebol",
#         "skate",
#         "patins",
#         "suplementos alimentares",
#         "tapete de yoga",
#         "bicicleta ergométrica",
#         "elíptico",
#         "luvas de boxe",
#         "barras de flexão",
#         "corda de pular",
#         "banco de musculação",
#         "faixas elásticas",
#         "step",
#         "bola de pilates",
#         "kettlebell",
#         "roupas de natação",
#         "mochila de hidratação",
#         "gorro de natação",
#         "óculos de natação",
#         "acessórios para bicicleta",
#         "smartphone",
#         "notebook",
#         "tablet",
#         "smart TV",
#         "headphone",
#         "smartwatch",
#         "câmera digital",
#         "console de videogame",
#         "caixa de som Bluetooth",
#         "home theater",
#         "projetor",
#         "fone de ouvido sem fio",
#         "monitor",
#         "disco rígido externo",
#         "impressora",
#         "roteador",
#         "mouse gamer",
#         "teclado",
#         "headset gamer",
#         "placa de vídeo",
#         "memória RAM",
#         "SSD",
#         "HD interno",
#         "microfone",
#         "leitor de e-book",
#         "controle remoto universal",
#         "antena digital",
#         "estabilizador",
#         "nobreak",
#         "câmera de segurança",
#         "drone",
#         "power bank",
#         "Chromecast",
#         "Apple TV",
#         "pen drive",
#         "carregador de celular",
#         "cabo HDMI",
#         "suporte para TV",
#         "adaptador USB",
#         "carregador sem fio",
#         "câmera instantânea",
#         "fone com cancelamento de ruído",
#         "placa-mãe",
#         "processador",
#         "kit de ferramentas eletrônicas",
#         "leitor de cartão de memória",
#         "lente para câmera",
#         "flash para câmera",
#         "livros",
#         "DVDs",
#         "blu-rays",
#         "e-books",
#         "CDs de música",
#         "revistas",
#         "áudiolivros",
#         "quadrinhos",
#         "mangás",
#         "box de séries",
#         "box de filmes",
#         "enciclopédias",
#         "mapas",
#         "calendários",
#         "agendas",
#         "boneca",
#         "carrinho de controle remoto",
#         "quebra-cabeça",
#         "Lego",
#         "jogos de tabuleiro",
#         "videogames",
#         "bonecos de ação",
#         "pelúcia",
#         "drones infantis",
#         "massinha de modelar",
#         "brinquedos educativos",
#         "blocos de montar",
#         "patinete",
#         "triciclo",
#         "piscina de bolinhas",
#         "casa de bonecas",
#         "carrinho de bebê de brinquedo",
#         "instrumentos musicais infantis",
#         "jogo de dardos",
#         "pista de carrinhos",
#         "castelo inflável",
#         "bolas esportivas",
#         "fantasias",
#         "jogos de cartas",
#         "kit de mágica",
#         "pneus",
#         "GPS automotivo",
#         "som automotivo",
#         "suporte veicular para celular",
#         "capa de volante",
#         "tapetes para carro",
#         "câmera de ré",
#         "kit de primeiros socorros para carro",
#         "carregador veicular",
#         "aspirador de pó automotivo",
#         "ração para pets",
#         "coleira",
#         "casinha para pets",
#         "brinquedos para pets",
#         "caixa de transporte",
#         "arranhador",
#         "comedouro automático",
#         "aquário",
#         "areia higiênica",
#         "bebedouro para pets"
#     ]

#     # Dicionário para armazenar os resultados
#     results = {}

#     # Pesquisar produtos por tipo
#     tasks = [fetch_product_type(product_type) for product_type in product_types]
#     responses = await asyncio.gather(*tasks)
#     results = dict(responses)

#     # Enviar a lista de produtos para a API
#     try:
#         result = send_products_to_api(results, ASSISTANT_ID_GROUP)
#     except HTTPException as he:
#         raise he
#     except Exception as e:
#         print(f"Erro ao enviar produtos para a API do assistente: {e}")
#         raise HTTPException(status_code=500, detail="Erro ao enviar produtos para a API do assistente.")

#     # Verificar se a resposta é vazia ou não é um JSON válido
#     if not result:
#         return {"error": "Resposta vazia ou não é um JSON válido."}
#     else:
#         try:
#             # Retornar a resposta em formato JSON
#             return json.loads(result)
#         except json.JSONDecodeError:
#             return {"error": "Resposta do assistente não é um JSON válido."}

# # Endpoint de pesquisa de produtos por tipo
# @app.post("/search_products_by_type/")
# async def search_products_by_type_endpoint():
#     return await search_products_by_type()

# Endpoint de saúde para verificação rápida
@app.get("/health")
async def health_check():
    return {"status": "OK"}
