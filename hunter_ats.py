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
    if not CATHO_ACTOR_ID:
        return [], "ID do Actor da Catho (CATHO_ACTOR_ID) não configurado."
    
    try:
        cookies = json.loads(CATHO_COOKIES_JSON) if isinstance(CATHO_COOKIES_JSON, str) else CATHO_COOKIES_JSON
    except Exception:
        return [], "Erro ao ler os cookies da Catho. Verifique a sintaxe da variável CATHO_COOKIES_JSON no .env."

    # Formata o Actor ID substituindo '/' por '~' exigido na API Apify
    actor_id_clean = CATHO_ACTOR_ID.replace("/", "~").strip()
    apify_url = f"https://api.apify.com/v2/acts/{actor_id_clean}/run-sync-get-dataset-items?token={APIFY_TOKEN}"
    
    payload = {
        "cathoCookies": cookies,
        "cookies": cookies,  # Mantém compatibilidade caso o actor espere 'cookies'
        "cargo": cargos_raw,
        "search": cargos_raw,
        "localizacao": localizacao,
        "location": localizacao,
        "limite": limite,
        "maxItems": limite
    }

    try:
        res = requests.post(apify_url, json=payload, timeout=120)
        if res.status_code not in (200, 201):
            return [], f"Erro no Scraper da Catho (HTTP {res.status_code}): {res.text[:150]}"

        dataset = res.json()
        if not isinstance(dataset, list):
            return [], "Catho Scraper não retornou dados válidos."

        # Padronização dos dados para o contrato esperado pelo frontend
        candidatos_normalizados = []
        for item in dataset:
            if not isinstance(item, dict):
                continue
            
            nome = item.get("nome") or item.get("name") or item.get("fullName") or "Candidato Catho"
            cargo = item.get("cargo") or item.get("title") or item.get("jobTitle") or cargos_raw
            email = item.get("email") or "Ver no Portal"
            telefone = item.get("telefone") or item.get("phone") or item.get("celular") or "Ver no Portal"
            link = item.get("link") or item.get("url") or item.get("profileUrl") or "https://www.catho.com.br"
            loc = item.get("localizacao") or item.get("location") or localizacao or "Não informada"

            candidatos_normalizados.append({
                "nome": nome,
                "cargo": cargo,
                "localizacao": loc,
                "email": email,
                "telefone": telefone,
                "link": link,
                "plataforma": "Catho"
            })

        return candidatos_normalizados[:limite], None

    except requests.exceptions.Timeout:
        return [], "Tempo limite esgotado ao pesquisar na Catho."
    except Exception as e:
        return [], f"Erro na integração com a Catho: {str(e)}"

def _buscar_google_xray(cargos_raw, localizacao, plataforma="linkedin", limite=20):
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
                if "catho.com.br" in url_perfil:
                    origem = "Catho (Google X-Ray)"
                elif "infojobs.com.br" in url_perfil:
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

    if plataforma_clean == "catho":
        candidatos, erro = _buscar_catho(cargos_raw, localizacao, limite)
        # Fallback para Google X-Ray se o Actor da Catho não retornar resultados ou der erro
        if not candidatos:
            candidatos_xray, erro_xray = _buscar_google_xray(cargos_raw, localizacao, "catho", limite)
            if candidatos_xray:
                return candidatos_xray, None
        return candidatos, erro

    elif plataforma_clean == "ambos":
        limite_por_lado = math.ceil(limite / 2)
        candidatos_catho, erro_catho = _buscar_catho(cargos_raw, localizacao, limite_por_lado)
        
        # Fallback para X-Ray da Catho caso o Actor venha vazio
        if not candidatos_catho:
            candidatos_catho, _ = _buscar_google_xray(cargos_raw, localizacao, "catho", limite_por_lado)
            
        candidatos_linkedin, erro_linkedin = _buscar_google_xray(cargos_raw, localizacao, "linkedin", limite_por_lado)
        combinados = candidatos_catho + candidatos_linkedin
        erros = [e for e in [erro_catho, erro_linkedin] if e]
        erro_final = " | ".join(erros) if erros else None
        if not combinados:
            return [], erro_final or "Nenhum candidato encontrado."
        return combinados[:limite], erro_final
    else:
        return _buscar_google_xray(cargos_raw, localizacao, plataforma_clean, limite)
