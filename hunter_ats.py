import hmac
import os
import requests
from flask import Flask, Response, render_template_string, request, jsonify
from dotenv import load_dotenv

# Carrega as variáveis do ficheiro .env
load_dotenv()

# Credenciais do Servidor Flask
APP_USER = os.getenv("APP_USER", "admin")
APP_PASSWORD = os.getenv("APP_PASSWORD", "admin")

# Token de Autenticação da Catho Empresas (obter via F12 no navegador)
CATHO_AUTH_TOKEN = os.getenv("CATHO_AUTH_TOKEN", "")

HEADERS_CATHO = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Authorization": CATHO_AUTH_TOKEN,
    "Content-Type": "application/json",
    "Origin": "https://www.catho.com.br",
    "Referer": "https://www.catho.com.br/empresas/busca-curriculos"
}

def buscar_candidatos_catho(cargo, localizacao, limite=20):
    """
    Realiza a pesquisa direta na API de busca de currículos do Catho Empresas.
    """
    if not CATHO_AUTH_TOKEN:
        return [], "ERRO CRÍTICO: Token da Catho ausente (CATHO_AUTH_TOKEN). Verifique o seu ficheiro .env!"

    # Endpoint interno de pesquisa da Catho Empresas (exemplo estrutural)
    endpoint_busca = "https://www.catho.com.br/empresas/api/v1/curriculos/busca"

    payload = {
        "busca": cargo,
        "cidade": localizacao,
        "paginacao": {
            "pagina": 1,
            "itensPorPagina": min(limite, 50)
        },
        "filtros": {
            "somenteComTelefone": True
        }
    }

    try:
        res = requests.post(endpoint_busca, headers=HEADERS_CATHO, json=payload, timeout=20)
        
        if res.status_code == 401:
            return [], "Erro de Autenticação (401): O token da Catho expirou ou é inválido. Faça login novamente no Catho Empresas e atualize o .env."
            
        if res.status_code != 200:
            return [], f"A Catho retornou o erro ({res.status_code}): {res.text}"

        dados = res.json()
        # Ajustar conforme a resposta real da API da Catho
        itens = dados.get("curriculos") or dados.get("data") or []

        if not itens:
            return [], f"Nenhum currículo encontrado na Catho para '{cargo}' em '{localizacao}'."

        candidatos = []
        for cv in itens:
            nome = cv.get("nome") or "Candidato Confidencial"
            cargo_atual = cv.get("cargoAtual") or cargo
            email = cv.get("email") or "Visível na plataforma"
            telefone = cv.get("telefone") or cv.get("celular") or "Visível na plataforma"
            id_curriculo = cv.get("idCurriculo") or cv.get("id")
            
            link_perfil = f"https://www.catho.com.br/empresas/curriculo/{id_curriculo}" if id_curriculo else "https://www.catho.com.br/empresas/"

            candidatos.append({
                "nome": nome,
                "cargo": cargo_atual,
                "localizacao": localizacao,
                "email": email,
                "telefone": telefone,
                "link_cv": link_perfil
            })

            if len(candidatos) >= limite:
                break

        return candidatos, None

    except Exception as e:
        return [], f"Falha na conexão com a Catho: {str(e)}"


app = Flask(__name__)

def _pedir_login():
    return Response(
        "Acesso restrito.", 401, {"WWW-Authenticate": 'Basic realm="Start RH - Catho Search"'}
    )

@app.before_request
def exigir_login():
    if not APP_USER or not APP_PASSWORD:
        return Response("Servidor sem APP_USER/APP_PASSWORD configurados.", 503)
    auth = request.authorization
    if not auth:
        return _pedir_login()
    user_ok = hmac.compare_digest(auth.username or "", APP_USER)
    pass_ok = hmac.compare_digest(auth.password or "", APP_PASSWORD)
    if not (user_ok and pass_ok):
        return _pedir_login()


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-PT">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Start RH - Pesquisa Catho Empresas</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen flex flex-col items-center p-6">
    <div class="max-w-5xl w-full bg-gray-800 rounded-xl shadow-2xl border border-gray-700 p-8 mt-6">
        
        <div class="flex items-center justify-between border-b border-gray-700 pb-6 mb-6">
            <div>
                <h1 class="text-2xl font-bold text-pink-500 flex items-center gap-2">
                    <i class="fa-solid fa-briefcase"></i> Busca Direta: Catho Empresas
                </h1>
                <p class="text-sm text-gray-400 mt-1">Integração com a base de dados de currículos da Catho.</p>
            </div>
        </div>

        <div class="space-y-4">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                    <label class="block text-sm font-medium text-gray-300 mb-1">Cargo Desejado:</label>
                    <input type="text" id="cargoInput" placeholder="Ex: Gerente de RH, Desenvolvedor Python" 
                        class="w-full bg-gray-900 border border-gray-700 rounded-lg p-3 text-gray-100 focus:outline-none focus:border-pink-500 transition text-sm">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-300 mb-1">Localização:</label>
                    <input type="text" id="localizacaoInput" value="São Paulo" placeholder="Ex: São Paulo, Rio de Janeiro" 
                        class="w-full bg-gray-900 border border-gray-700 rounded-lg p-3 text-gray-100 focus:outline-none focus:border-pink-500 transition text-sm">
                </div>
            </div>

            <div>
                <label class="block text-sm font-medium text-gray-300 mb-1">
                    Quantidade máxima de candidatos:
                </label>
                <input type="number" id="limiteInput" value="20" min="1" max="50"
                    class="w-32 bg-gray-900 border border-gray-700 rounded-lg p-2 text-gray-100 focus:outline-none focus:border-pink-500 transition font-mono text-sm">
            </div>

            <button id="btnProcessar" onclick="processarHunting()" 
                class="w-full bg-pink-600 hover:bg-pink-700 text-white font-bold py-3 px-6 rounded-lg transition flex items-center justify-center gap-2 shadow-lg shadow-pink-500/20">
                <i class="fa-solid fa-magnifying-glass"></i> Buscar na Catho
            </button>
        </div>

        <div id="loading" class="hidden my-8 text-center">
            <div class="inline-block animate-spin rounded-full h-10 w-10 border-4 border-pink-500 border-t-transparent"></div>
            <p class="text-gray-400 text-sm mt-3 animate-pulse">A comunicar com a API da Catho Empresas...</p>
        </div>

        <div id="resultadoContainer" class="hidden mt-8 border-t border-gray-700 pt-6">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-lg font-semibold text-gray-200 flex items-center gap-2">
                    <i class="fa-solid fa-list text-pink-500"></i> Currículos Encontrados:
                </h2>
                <span id="totalBadge" class="bg-pink-500/10 text-pink-400 text-xs px-3 py-1 rounded-full border border-pink-500/20 font-mono"></span>
            </div>
            
            <div id="logList" class="space-y-3 font-sans text-sm"></div>
        </div>
    </div>

    <script>
        async function processarHunting() {
            const cargo = document.getElementById('cargoInput').value.trim();
            const localizacao = document.getElementById('localizacaoInput').value.trim();
            const limite = parseInt(document.getElementById('limiteInput').value) || 20;
            
            if (!cargo) return alert('Por favor, informe o cargo.');

            const btn = document.getElementById('btnProcessar');
            const loading = document.getElementById('loading');
            const resultadoContainer = document.getElementById('resultadoContainer');
            const logList = document.getElementById('logList');
            const totalBadge = document.getElementById('totalBadge');

            btn.disabled = true;
            btn.classList.add('opacity-50', 'cursor-not-allowed');
            loading.classList.remove('hidden');
            resultadoContainer.classList.add('hidden');
            logList.innerHTML = '';

            try {
                const response = await fetch('/api/buscar_candidatos', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cargo: cargo, localizacao: localizacao, limite: limite })
                });
                const data = await response.json();
                
                loading.classList.add('hidden');
                resultadoContainer.classList.remove('hidden');

                if (data.status === 'success') {
                    totalBadge.innerText = `${data.contatos.length} Candidato(s)`;

                    if (data.contatos.length === 0) {
                        logList.innerHTML = `<p class="text-rose-400 p-3 bg-rose-500/10 rounded border border-rose-500/20"><i class="fa-solid fa-triangle-exclamation"></i> <b>Aviso:</b> ${data.erro}</p>`;
                    } else {
                        let tableHtml = `
                            <div class="overflow-x-auto">
                                <table class="w-full text-left border-collapse border border-gray-700">
                                    <thead>
                                        <tr class="bg-gray-900 text-pink-400 border-b border-gray-700 text-xs uppercase font-mono">
                                            <th class="p-3">Nome</th>
                                            <th class="p-3">Cargo Atual</th>
                                            <th class="p-3">E-mail</th>
                                            <th class="p-3">Telefone</th>
                                            <th class="p-3 text-center">Ação</th>
                                        </tr>
                                    </thead>
                                    <tbody class="divide-y divide-gray-700 bg-gray-800/50">`;

                        data.contatos.forEach(c => {
                            tableHtml += `
                                <tr class="hover:bg-gray-800 transition">
                                    <td class="p-3 font-semibold text-gray-100">${c.nome}</td>
                                    <td class="p-3 text-gray-300">${c.cargo}</td>
                                    <td class="p-3 font-mono text-xs text-pink-300/90">${c.email}</td>
                                    <td class="p-3 font-mono text-xs text-emerald-400">${c.telefone}</td>
                                    <td class="p-3 text-center">
                                        <a href="${c.link_cv}" target="_blank" class="inline-flex items-center gap-1 bg-pink-600/20 hover:bg-pink-600/40 text-pink-400 border border-pink-500/30 px-3 py-1 rounded-md text-xs transition"><i class="fa-solid fa-file-lines"></i> Ver CV na Catho</a>
                                    </td>
                                </tr>`;
                        });

                        tableHtml += `</tbody></table></div>`;
                        logList.innerHTML = tableHtml;
                    }
                } else {
                    logList.innerHTML = `<p class="text-rose-500 p-3 bg-rose-500/10 rounded border border-rose-500/20"><i class="fa-solid fa-bomb"></i> Erro no servidor: ${data.message}</p>`;
                }
            } catch (err) {
                loading.classList.add('hidden');
                resultadoContainer.classList.remove('hidden');
                logList.innerHTML = `<p class="text-rose-500">Erro na requisição: ${err.message}</p>`;
            } finally {
                btn.disabled = false;
                btn.classList.remove('opacity-50', 'cursor-not-allowed');
            }
        }
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/buscar_candidatos", methods=["POST"])
def api_buscar_candidatos():
    data = request.json or {}
    cargo = data.get("cargo", "").strip()
    localizacao = data.get("localizacao", "").strip()
    try:
        limite = max(1, min(int(data.get("limite", 20)), 50))
    except (TypeError, ValueError):
        limite = 20

    if not cargo:
        return jsonify({"status": "error", "message": "O campo 'cargo' é obrigatório."}), 400

    contatos, erro_catho = buscar_candidatos_catho(cargo, localizacao, limite=limite)
    
    return jsonify({
        "status": "success",
        "cargo": cargo,
        "localizacao": localizacao,
        "contatos": contatos,
        "erro": erro_catho
    })

if __name__ == "__main__":
    porta = int(os.getenv("PORT", "5000"))
    print("\n--- SERVIDOR LOCAL START RH (CATHO SEARCH) INICIADO ---")
    print(f"Aceda no navegador: http://localhost:{porta}\n")
    app.run(host="127.0.0.1", port=porta, debug=False)
