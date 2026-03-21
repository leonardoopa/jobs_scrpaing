import logging
import os
import json
import time
import hashlib
import redis
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dotenv import load_dotenv


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

logger = logging.getLogger(__name__)


class LinkedinWorker:
    def __init__(self):
        # Pegamos apenas o cookie mágico do .env agora
        self.li_at_cookie = os.getenv("LINKEDIN_LI_AT")

        # Conexão com Redis
        host_redis = os.getenv("REDIS_HOST", "localhost")
        try:
            self.redis_client = redis.Redis(
                host=host_redis, port=6379, db=0, decode_responses=True
            )
            self.redis_client.ping()
        except Exception as e:
            logger.warning(f"Não foi possível conectar ao Redis: {e}")

    def _gerar_id_unico(self, link):
        """Cria um ID único baseado no link da vaga (removendo parâmetros de rastreio)"""
        link_limpo = link.split("?")[0] if "?" in link else link
        return hashlib.md5(link_limpo.encode("utf-8")).hexdigest()

    def carregar_mais_vagas(self, driver):
        """Rola o painel esquerdo do LinkedIn para forçar o carregamento de mais vagas."""
        logger.info("Iniciando a rolagem para carregar vagas da página...")
        quantidade_anterior = 0
        tentativas_sem_novas = 0

        while True:
            job_cards = driver.find_elements(By.CSS_SELECTOR, ".job-card-container")
            quantidade_atual = len(job_cards)

            if quantidade_atual == quantidade_anterior:
                tentativas_sem_novas += 1
                if tentativas_sem_novas >= 3:
                    break
            else:
                tentativas_sem_novas = 0

            quantidade_anterior = quantidade_atual

            if job_cards:
                driver.execute_script(
                    "arguments[0].scrollIntoView(true);", job_cards[-1]
                )
                time.sleep(2)

        logger.info(f"Rolagem concluída! Total de vagas listadas: {quantidade_atual}")
        return driver.find_elements(By.CSS_SELECTOR, ".job-card-container")

    def varrer_vagas(self, lista_cargos, lista_cidades, max_paginas=2):
        if not self.li_at_cookie:
            logger.error(
                "Erro: Cookie LINKEDIN_LI_AT não encontrado no .env. Abortando."
            )
            return

        options = webdriver.ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")

        # --- Configurações vitais para o Docker ---
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        # ------------------------------------------

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=options
        )
        wait = WebDriverWait(driver, 10)
        vagas_extraidas = []

        try:
            # 1. Injeção de Cookie (O pulo do gato)
            logger.info("Injetando cookie de sessão do LinkedIn...")
            driver.get("https://www.linkedin.com")
            time.sleep(2)

            driver.add_cookie(
                {"name": "li_at", "value": self.li_at_cookie, "domain": ".linkedin.com"}
            )
            logger.info("Sessão autenticada com sucesso!")

            # 2. Varredura da Matriz (Cargos x Cidades)
            for cidade in lista_cidades:
                for cargo in lista_cargos:
                    logger.info(f"\n🔍 [LinkedIn] Minerando: {cargo} em {cidade}")

                    # Monta a URL dinâmica de busca do LinkedIn
                    busca_url = f"https://www.linkedin.com/jobs/search/?keywords={cargo}&location={cidade}"
                    driver.get(busca_url)
                    time.sleep(5)

                    for pagina_atual in range(1, max_paginas + 1):
                        logger.info(
                            f"--- Processando {cargo} em {cidade} [Página {pagina_atual}] ---"
                        )
                        job_cards = self.carregar_mais_vagas(driver)

                        for index, card in enumerate(job_cards):
                            try:
                                driver.execute_script(
                                    "arguments[0].scrollIntoView(true);", card
                                )
                                card.click()
                                time.sleep(1.5)

                                # Extração
                                titulo_el = wait.until(
                                    EC.presence_of_element_located(
                                        (
                                            By.CSS_SELECTOR,
                                            ".job-details-jobs-unified-top-card__job-title",
                                        )
                                    )
                                )
                                titulo = titulo_el.text.strip()

                                sobre_el = wait.until(
                                    EC.presence_of_element_located(
                                        (By.CSS_SELECTOR, ".jobs-description__content")
                                    )
                                )
                                descricao = sobre_el.text.strip()

                                # Pegar Link da vaga (o LinkedIn as vezes usa a tag A principal do card)
                                link_vaga = card.find_element(
                                    By.CSS_SELECTOR,
                                    "a.job-card-list__title, a.job-card-container__link",
                                ).get_attribute("href")

                                # Tenta pegar empresa
                                try:
                                    empresa = driver.find_element(
                                        By.CSS_SELECTOR,
                                        ".job-details-jobs-unified-top-card__company-name",
                                    ).text.strip()
                                except:
                                    empresa = "Não informado"

                                # --- O PADRÃO UNIVERSAL PARA O GEMINI ---
                                id_unico = self._gerar_id_unico(link_vaga)

                                vaga_padronizada = {
                                    "id_vaga": id_unico,
                                    "plataforma": "LinkedIn",
                                    "cargo_buscado": cargo,
                                    "titulo": titulo,
                                    "empresa": empresa,
                                    "localizacao": cidade,
                                    "modalidade": "Não informado",  # Filtros avançados podem definir isso depois
                                    "regime": "Não informado",
                                    "salario": "Não informado",
                                    "descricao": descricao,
                                    "link": link_vaga,
                                }

                                vagas_extraidas.append(vaga_padronizada)

                                # Salva no Redis usando HSET
                                if hasattr(self, "redis_client"):
                                    self.redis_client.hset(
                                        "vagas_database",
                                        id_unico,
                                        json.dumps(vaga_padronizada),
                                    )

                            except Exception as e:
                                logger.error(
                                    f"Erro ao extrair vaga {index + 1}. Pulando..."
                                )
                                continue

                        # Lógica da paginação do LinkedIn (clicar nos botões numéricos no final da lista)
                        if pagina_atual < max_paginas:
                            try:
                                proxima_pagina_num = pagina_atual + 1
                                xpath_botao = f"//button[@aria-label='Página {proxima_pagina_num}' or @aria-label='Page {proxima_pagina_num}']"
                                botao_proxima = wait.until(
                                    EC.presence_of_element_located(
                                        (By.XPATH, xpath_botao)
                                    )
                                )
                                driver.execute_script(
                                    "arguments[0].scrollIntoView(true);", botao_proxima
                                )
                                time.sleep(1)
                                driver.execute_script(
                                    "arguments[0].click();", botao_proxima
                                )
                                time.sleep(4)
                            except Exception:
                                logger.info("Fim da paginação ou botão não encontrado.")
                                break

            # Salva backup JSON
            with open("vagas_linkedin.json", "w", encoding="utf-8") as f:
                json.dump(vagas_extraidas, f, ensure_ascii=False, indent=4)
            logger.info("Extração do LinkedIn concluída com sucesso!")

        except Exception as e:
            logger.error(f"Ocorreu um erro crítico no fluxo: {e}")

        finally:
            driver.quit()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    worker = LinkedinWorker()
    worker.varrer_vagas(["Desenvolvedor Backend"], ["Recife"], max_paginas=1)
