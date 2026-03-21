import asyncio
import logging
import httpx
from bs4 import BeautifulSoup
import json
import redis
import os
import hashlib
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

logger = logging.getLogger(__name__)


class InfoJobsWorker:
    def __init__(self):
        self.base_url = os.getenv(
            "INFOJOBS_BASE_URL", "https://www.infojobs.com.br/vagas-de-emprego.aspx"
        )
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        self.redis_client = self._conectar_redis()

    def _conectar_redis(self):
        """Gerencia a conexão com o Redis com fallback seguro."""
        host = os.getenv("REDIS_HOST", "localhost")
        port = int(os.getenv("REDIS_PORT", 6379))

        try:
            client = redis.Redis(
                host=host, port=port, db=0, decode_responses=True, socket_timeout=3
            )
            client.ping()
            logger.info(f"Conectado ao Redis com sucesso ({host}:{port})")
            return client
        except Exception as e:
            logger.warning(
                f"Redis indisponível ({host}:{port}). O bot vai rodar no modo de testes (apenas exibição)."
            )
            return None

    def _gerar_id_unico(self, link):
        """Cria um ID único baseado no link da vaga (MD5 Hash)"""
        return hashlib.md5(link.encode("utf-8")).hexdigest()

    def _salvar_vaga(self, vaga_padronizada):
        """Isola a lógica de persistência de dados no banco."""
        if self.redis_client:
            try:
                self.redis_client.hset(
                    "vagas_database",
                    vaga_padronizada["id_vaga"],
                    json.dumps(vaga_padronizada),
                )
            except Exception as e:
                logger.error(
                    f"Erro ao salvar vaga {vaga_padronizada['titulo']} no Redis: {e}"
                )
        else:
            # Em ambiente local sem banco
            pass

    async def varrer_vagas(self, lista_cargos, lista_cidades, max_paginas=2):
        """Método Orquestrador do Worker."""
        async with httpx.AsyncClient(headers=self.headers, timeout=20.0) as client:
            for cidade in lista_cidades:
                for cargo in lista_cargos:
                    logger.info(f"\n [InfoJobs] Minerando: {cargo} em {cidade}")
                    await self._extrair_paginas(client, cargo, cidade, max_paginas)
                    await asyncio.sleep(2)

    async def _extrair_paginas(self, client, cargo, cidade, max_paginas):
        """Faz as requisições HTTP e varre a paginação."""
        busca_formatada = f"{cargo} {cidade}".strip()

        for pagina in range(1, max_paginas + 1):
            params = {"Palabra": busca_formatada, "page": pagina}

            try:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")

                cards = soup.select(
                    "div.js_rowVaga, div[class*='vaga'], div[class*='card-job'], div.js_card, div.card"
                )

                if not cards:
                    logger.info(f"Fim dos resultados na página {pagina}.")
                    break

                vagas_salvas_nesta_pagina = 0

                for card in cards:
                    if not hasattr(card, "find"):
                        continue

                    # 1. TÍTULO E LINK
                    tag_h2 = card.find("h2")
                    tag_a = card.find(
                        "a"
                    )  # Pega o primeiro link do card como "plano B" imediato

                    if tag_h2:
                        titulo = tag_h2.get_text(strip=True)
                        # Se tiver um link dentro do h2, a gente prefere usar ele
                        link_no_h2 = tag_h2.find("a")
                        if link_no_h2:
                            tag_a = link_no_h2
                    else:
                        # Se não tem h2 nenhum, o título será o texto do próprio link
                        titulo = tag_a.get_text(strip=True) if tag_a else ""

                    link = tag_a.get("href", "") if tag_a else ""

                    if (
                        not link
                        or not titulo
                        or titulo.lower() in ["veja mais", "vagas premium"]
                    ):
                        continue

                    if link.startswith("/"):
                        link = "https://www.infojobs.com.br" + link

                    divs_muted = card.find_all("div", class_="text-muted")
                    empresa = (
                        divs_muted[0].get_text(strip=True)
                        if len(divs_muted) > 0
                        else "Confidencial"
                    )
                    local = (
                        divs_muted[1].get_text(strip=True)
                        if len(divs_muted) > 1
                        else cidade
                    )
                    descricao = (
                        divs_muted[2].get_text(strip=True)
                        if len(divs_muted) > 2
                        else "Acesse o link para ver a descrição."
                    )
                    if (
                        cidade.lower() not in local.lower()
                        and "remoto" not in local.lower()
                    ):
                        continue

                    vaga_padronizada = {
                        "id_vaga": self._gerar_id_unico(link),
                        "plataforma": "InfoJobs",
                        "cargo_buscado": cargo,
                        "titulo": titulo,
                        "empresa": empresa,
                        "localizacao": local,
                        "modalidade": "Não informado",
                        "regime": "Não informado",
                        "salario": "Não informado",
                        "descricao": descricao,
                        "link": link,
                    }

                    self._salvar_vaga(vaga_padronizada)
                    vagas_salvas_nesta_pagina += 1
                    logger.info(f" ---> Capturada: {titulo}")

                logger.info(
                    f"Página {pagina} concluída: {vagas_salvas_nesta_pagina} vagas válidas capturadas."
                )

            except Exception as e:
                logger.error(f"Erro ao processar página {pagina}: {e}")
                break


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    async def testar_infojobs():
        worker = InfoJobsWorker()
        await worker.varrer_vagas(["Desenvolvedor"], [""], max_paginas=1)

    asyncio.run(testar_infojobs())
