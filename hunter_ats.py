import hmac
import json
import math
import os
import re
from flask import Flask, Response, render_template_string, request, jsonify
import requests
from dotenv import load_dotenv

load_dotenv()

# Variáveis de ambiente
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY", "")

APP_USER = os.getenv("APP_USER", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")

# Variáveis do Actor Logado da Catho
CATHO_ACTOR_ID = os.getenv("CATHO_ACTOR_ID", "")
CATHO_COOKIES_JSON = os.getenv("CATHO_COOKIES_JSON", "[]")

HEADERS_APOLLO = {
    "Cache-Control": "no-cache",
    "Content-Type": "application/json",
    "x-api-key": APOLLO_API_KEY,
}

PLATFORM_SITES = {
    "linkedin": 'site:linkedin.com/in/',
    "catho": '(site:catho.com.br "currículo" OR site:catho.com.br/profissionais/)',
    "infojobs": '(site:infojobs.com.br/cv/ OR site:infojobs.com.br/candidato/)',
    "indeed": 'site:br.indeed.com/r/',
    "vagas": 'site:vagas.com.br "curriculo"',
    "todas": '(site:linkedin.com/in/ OR site:catho.com.br OR site:infojobs.com.br/cv/ OR site:br.indeed.com/r/)'
}

JOB_URL_KEYWORDS = [
    "/vagas/", "/vaga/", "/vagas-de-emprego/", "/jobs/", "/job/",
    "/oportunidades/", "/trabalhe-conosco/", "/emprego/", "/oferta-de-trabalho/"
]

def e_url_de_vaga(url):
    url_lower = url.lower()
    return any(keyword in url_lower for keyword in JOB_URL_KEYWORDS)

def formatar_localizacao_query(loc_raw):
    loc_limpa = loc_raw.strip()
    if not loc_limpa:
        return ""
    if "," in loc_limpa:
        partes = [p.strip() for p in loc_limpa.split(",") if p.strip()]
        return f'("{partes[0]}" OR "{loc_limpa}")'
    elif "-" in loc_limpa:
        partes = [p.strip() for p in loc_limpa.split("-") if p.strip()]
        return f'("{partes[0]}" OR "{loc_limpa}")'
    return f'"{loc_limpa}"'

def extrair_nome_e_cargo(titulo_google):
    if not titulo_google:
        return "Candidato", "Não informado"
    
    titulo_limpo = re.sub(
        r"\s*[\-\|–]\s*(LinkedIn|Catho|InfoJobs|Indeed|Vagas|Curriculo|Resumo).*$", 
        "", 
        str(titulo_google), 
        flags=re.IGNORECASE
    )
    partes = re.split(r"\s*[\-\|–]\s*", titulo_limpo)
    
    nome = partes[0].strip() if len(partes) > 0 else "Candidato"
    cargo = partes[1].strip() if len(partes) > 1 else "Não informado"
    
    return nome, cargo

def enriquecer_contato_apollo(linkedin_url):
    if not APOLLO_API_KEY or not linkedin_url or "linkedin.com/in/" not in linkedin_url:
        return "Não disponível", "Não disponível"

    url_match = "https://api.apollo.io/v1/people/match"
    payload = {
        "api_key": APOLLO_API_KEY,
        "details_api_key": APOLLO_API_KEY,
        "linkedin_url": linkedin_url
    }

    try:
        res = requests.post(url_match, headers=HEADERS_APOLLO, json=payload, timeout=3)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, dict):
                person = data.get("person") or {}
                email = person.get("email") or "Não disponível"
                telefone = "Não disponível"
                phones = person.get("phone_numbers") or []
                if isinstance(phones, list) and len(phones) > 0 and isinstance(phones[0], dict):
                    telefone = phones[0].get("sanitized_number") or phones[0].get("raw_number") or "Não disponível"
                elif person.get("sanitized_phone_number"):
                    telefone = person.get("sanitized_phone_number")
                return email, telefone
    except Exception:
        pass

    return "Não disponível", "Não disponível"

def _buscar_catho(cargos_raw, localizacao, limite):
    """Busca diretamente na Catho através do Actor logado do Apify."""
    if not CATHO_ACTOR_ID:
        return [], "ID do Actor da Catho (CATHO_ACTOR_ID) não configurado."
    
    try:
        cookies = json.loads(CATHO_COOKIES_JSON)
    except Exception:
        return [], "Erro ao ler os cookies da Catho. Verifique a variável CATHO_COOKIES_JSON."

    apify_url = f"https://api.apify.com/v2/acts/{CATHO_ACTOR_ID}/run-sync-get-dataset-items?token={APIFY_TOKEN}"
    
    payload = {
        "cathoCookies": cookies,
        "cargo": cargos_raw,
        "localizacao": localizacao,
        "limite": limite
    }

    try:
        res = requests.post(apify_url, json=payload, timeout=120)
        if res.status_code not in (200, 201):
            return [], f"Erro no Scraper da Catho (HTTP {res.status_code}): {res.text[:150]}"

        dataset = res.json()
        if not isinstance(dataset, list):
            return [], "Catho Scraper não retornou dados válidos."

        return dataset, None
    except requests.exceptions.Timeout:
        return [], "Tempo limite esgotado ao pesquisar na Catho."
    except Exception as e:
        return [], f"Erro na integração com a Catho: {str(e)}"

def _buscar_google_xray(cargos_raw, localizacao, plataforma="linkedin", limite=20):
    """Busca no LinkedIn ou outras redes via Google Search Scraper do Apify."""
    cargos_lista = [c.strip() for c in cargos_raw.split(",") if c.strip()]
    if not cargos_lista:
        return [], "Por favor, informe ao menos um cargo."

    loc_query = formatar_localizacao_query(localizacao)
    site_prefix = PLATFORM_SITES.get(plataforma, PLATFORM_SITES["linkedin"])
    
    queries_lista = [f'{site_prefix} "{cargo}" {loc_query}' for cargo in cargos_lista]
    query_final_str = "\n".join(queries_lista)
    
    max_paginas = min(10, max(1, math.ceil(limite / 10)))
    apify_url = f"https://api.apify.com/v2/acts/apify~google-search-scraper/run-sync-get-dataset-items?token={APIFY_TOKEN}"
    
    payload = {
        "queries": query_final_str,
        "maxPagesPerQuery": max_paginas,
        "resultsPerPage": 10
    }

    try:
        res = requests.post(apify_url, json=payload, timeout=60)
        if res.status_code not in (200, 201):
            return [], f"Apify retornou erro HTTP {res.status_code}: {res.text[:150]}"

        try:
            dataset = res.json()
        except Exception:
            return [], "Apify retornou uma resposta em formato inválido."

        if not dataset or not isinstance(dataset, list):
            return [], "Nenhum resultado retornado do Apify."

        candidatos = []
        urls_vistas = set()

        for pagina_busca in dataset:
            if not isinstance(pagina_busca, dict):
                continue
            organics = pagina_busca.get("organicResults") or []
            
            for item in organics:
                if not isinstance(item, dict):
                    continue
                url_perfil = item.get("url", "")
                
                if not url_perfil or url_perfil in urls_vistas or e_url_de_vaga(url_perfil):
                    continue

                urls_vistas.add(url_perfil)

                titulo_item = item.get("title", "")
                snippet = item.get("description", "")
                nome, cargo_extraido = extrair_nome_e_cargo(titulo_item)
                cargo_final = cargo_extraido if cargo_extraido != "Não informado" else cargos_lista[0]

                if "linkedin.com/in/" in url_perfil:
                    email, telefone = enriquecer_contato_apollo(url_perfil)
                else:
                    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', snippet)
                    phone_match = re.search(r'\(?\d{2}\)?\s?\d{4,5}[-\s]?\d{4}', snippet)
                    
                    email = email_match.group(0) if email_match else "Ver no Portal"
                    telefone = phone_match.group(0) if phone_match else "Ver no Portal"

                origem = "LinkedIn"
                if "infojobs.com.br" in url_perfil:
                    origem = "InfoJobs"
                elif "indeed.com" in url_perfil:
                    origem = "Indeed"
                elif "vagas.com.br" in url_perfil:
                    origem = "Vagas.com"

                candidatos.append({
                    "nome": nome,
                    "cargo": cargo_final,
                    "localizacao": localizacao if localizacao else "Não informada",
                    "email": email,
                    "telefone": telefone,
                    "link": url_perfil,
                    "plataforma": origem
                })

                if len(candidatos) >= limite:
                    break

            if len(candidatos) >= limite:
                break

        return candidatos, None

    except requests.exceptions.Timeout:
        return [], "O tempo limite de busca esgotou no servidor Apify."
    except Exception as e:
        return [], f"Erro ao processar busca: {str(e)}"

def buscar_candidatos_apify(cargos_raw, localizacao, plataforma="linkedin", limite=20):
    if not APIFY_TOKEN:
        return [], "Token do Apify ausente (APIFY_TOKEN). Verifique as variáveis de ambiente!"

    plataforma_clean = plataforma.lower()

    # 1. BUSCA EXCLUSIVA NA CATHO
    if plataforma_clean == "catho":
        return _buscar_catho(cargos_raw, localizacao, limite)

    # 2. BUSCA EM AMBOS (LINKEDIN + CATHO)
    elif plataforma_clean == "ambos":
        limite_por_lado = math.ceil(limite / 2)
        
        candidatos_catho, erro_catho = _buscar_catho(cargos_raw, localizacao, limite_por_lado)
        candidatos_linkedin, erro_linkedin = _buscar_google_xray(cargos_raw, localizacao, "linkedin", limite_por_lado)

        combinados = candidatos_catho + candidatos_linkedin
        
        erros = [e for e in [erro_catho, erro_linkedin] if e]
        erro_final = " | ".join(erros) if erros else None

        if not combinados:
            return [], erro_final or "Nenhum candidato encontrado no LinkedIn nem na Catho."

        return combinados[:limite], erro_final

    # 3. BUSCA EM OUTRAS PLATAFORMAS (LINKEDIN, INFOJOBS, ETC)
    else:
        return _buscar_google_xray(cargos_raw, localizacao, plataforma_clean, limite)


# --- SERVIDOR FLASK ---
app = Flask(__name__)

@app.errorhandler(Exception)
def tratar_erro_generico(e):
    code = getattr(e, "code", 500)
    return jsonify({"status": "error", "message": f"Erro interno ({code}): {str(e)}"}), code

def _pedir_login():
    return Response(
        "Acesso restrito.", 401, {"WWW-Authenticate": 'Basic realm="Start RH - Candidate Search"'}
    )

@app.before_request
def exigir_login():
    if not APP_USER or not APP_PASSWORD:
        if request.path.startswith("/api/"):
            return jsonify({"status": "error", "message": "APP_USER/APP_PASSWORD não configurados."}), 503
        return Response("APP_USER/APP_PASSWORD não configurados.", 503)

    auth = request.authorization
    if not auth:
        return _pedir_login()
    user_ok = hmac.compare_digest(auth.username or "", APP_USER)
    pass_ok = hmac.compare_digest(auth.password or "", APP_PASSWORD)
    if not (user_ok and pass_ok):
        return _pedir_login()


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Start RH - Busca de Candidatos</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen flex flex-col items-center p-6">
    <div class="max-w-6xl w-full bg-gray-800 rounded-
