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
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
from openai import OpenAI

# Configurar o cliente OpenAI com a chave correta
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ASSISTANT_ID = os.environ.get('ASSISTANT_ID')
ASSISTANT_ID_GROUP = os.environ.get('ASSISTANT_ID_GROUP')
SEARXNG_ENDPOINTS = [
    "https://meutudo-search-u69koy43zgt5zonu.onrender.com",
    "https://mt-pesquisa-2uw5m7edjspsu5xh.onrender.com",
    "https://pesquisa-mt-q7m2taf0ob.koyeb.app/",
    "https://search-mt-w5r6poyq8ojutb2w.onrender.com",
    "https://smoggy-yasmeen-lfelipeapo-97ab6e01.koyeb.app/"
]
SECRET_KEY = os.getenv('SECRET_KEY')
ALLOWED_IPS = os.getenv('ALLOWED_IPS', '').split(',')
ALLOWED_DOMAINS = os.getenv('ALLOWED_DOMAINS', '').split(',')

app = FastAPI()

@app.post("/generate_token")
async def generate_token(request: Request):
    # Configurações para validação
    SECRET_KEY = os.getenv('SECRET_KEY')
    ALLOWED_IPS = os.getenv('ALLOWED_IPS', '').split(',')
    ALLOWED_DOMAINS = os.getenv('ALLOWED_DOMAINS', '').split(',')

    # Validação de IP
    client_ip = request.client.host
    if client_ip not in ALLOWED_IPS:
        raise HTTPException(status_code=403, detail='IP não autorizado!')

    # Validação de Domínio
    referer = request.headers.get('Referer')
    if not referer:
        raise HTTPException(status_code=403, detail='Referer é necessário!')

    domain = referer.split('/')[2]
    if domain not in ALLOWED_DOMAINS:
        raise HTTPException(status_code=403, detail='Domínio não autorizado!')

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
        # Verificação do token JWT
        token = request.headers.get('Authorization')
        if not token:
            raise HTTPException(status_code=403, detail='Token é necessário!')

        try:
            jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=403, detail='Token expirado!')
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=403, detail='Token inválido!')

        # Validação de IP
        client_ip = request.client.host
        if client_ip not in ALLOWED_IPS:
            raise HTTPException(status_code=403, detail='IP não autorizado!')

        # Validação de Domínio
        referer = request.headers.get('Referer')
        if referer:
            domain = referer.split('/')[2]
            if domain not in ALLOWED_DOMAINS:
                raise HTTPException(status_code=403, detail='Domínio não autorizado!')

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

# Função de balanceamento de carga e failover para requisição HTTP

@backoff.on_exception(backoff.expo, httpx.RequestError, max_tries=3)
async def load_balancer_request(data, headers, timeout=30):
    for endpoint in SEARXNG_ENDPOINTS:
        try:
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

# Função para validar e sanitizar a entrada do nome do produto
def validate_and_sanitize_product_name(product_name: str):
    # Validar se existe nome de produto
    if len(product_name.strip()) == 0:
        raise HTTPException(status_code=400, detail="Nome de produto não informado.")

    # Limitar o tamanho do nome do produto para evitar ataques de buffer overflow
    if len(product_name) > 50:
        raise HTTPException(status_code=400, detail="Nome do produto excede o tamanho permitido.")

    # Sanitização básica contra XSS
    product_name = html.escape(product_name)

    # Expressão regular para permitir apenas letras, números, espaço, e alguns símbolos seguros (- e _)
    if not re.match(r"^[a-zA-Z0-9 _-]+$", product_name):
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
            "q": f"{product_name} (site:zoom.com.br OR site:buscape.com.br)",
            "format": "json"
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
        products = search_results.get('results', [])
        print(f"Produtos obtidos: {products}")
        result = send_products_to_api(products, ASSISTANT_ID)
        print(f"Resposta do assistente: {result}")
        return json.loads(result)
    except json.JSONDecodeError:
        print("Erro ao converter a resposta do assistente para JSON.")
        return {"error": "Resposta do assistente não é um JSON válido."}
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Erro ao processar a resposta do assistente: {e}")
        return {"error": f"Erro ao processar a resposta do assistente: {e}"}

# Função auxiliar para buscar produtos por tipo
async def fetch_product_type(product_type):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/58.0.3029.110 Safari/537.3",
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive"
        }
        data = {
            "q": f"{product_type} (site:zoom.com.br OR site:buscape.com.br)",
            "format": "json"
        }
        search_response = await load_balancer_request(data, headers)
        # Verifica se o status da resposta é 200 (OK)
        if search_response.status_code != 200:
            return (product_type, {"error": "Falha na pesquisa."})
        # Tenta fazer o parsing do JSON
        search_results = search_response.json()
        products = search_results.get('results', [])
        return (product_type, products)
    except httpx.RequestError as e:
        print(f"Erro ao conectar ao serviço de pesquisa para o tipo {product_type}: {e}")
        return (product_type, {"error": "Falha na pesquisa."})
    except json.JSONDecodeError:
        return (product_type, {"error": "Resposta do serviço de pesquisa não é um JSON válido."})
    except Exception as e:
        print(f"Erro inesperado ao buscar o tipo {product_type}: {e}")
        return (product_type, {"error": "Falha na pesquisa."})
        
# Função para pesquisar produtos por tipo
async def search_products_by_type():
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

    # Dicionário para armazenar os resultados
    results = {}

    # Pesquisar produtos por tipo
    tasks = [fetch_product_type(product_type) for product_type in product_types]
    responses = await asyncio.gather(*tasks)
    results = dict(responses)

    # Enviar a lista de produtos para a API
    try:
        result = send_products_to_api(results, ASSISTANT_ID_GROUP)
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Erro ao enviar produtos para a API do assistente: {e}")
        raise HTTPException(status_code=500, detail="Erro ao enviar produtos para a API do assistente.")

    # Verificar se a resposta é vazia ou não é um JSON válido
    if not result:
        return {"error": "Resposta vazia ou não é um JSON válido."}
    else:
        try:
            # Retornar a resposta em formato JSON
            return json.loads(result)
        except json.JSONDecodeError:
            return {"error": "Resposta do assistente não é um JSON válido."}

# Endpoint de pesquisa de produtos por tipo
@app.post("/search_products_by_type/")
async def search_products_by_type_endpoint():
    return await search_products_by_type()

# Endpoint de saúde para verificação rápida
@app.get("/health")
async def health_check():
    return {"status": "OK"}
