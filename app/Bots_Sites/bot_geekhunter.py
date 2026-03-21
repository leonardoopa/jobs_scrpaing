import logging
import json
import time
import os
import hashlib
import redis
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()


class GeekHunterWorker:
    def __init__(self):
        self.base_url = os.getenv(
            "GEEKHUNTER_BASE_URL", "https://www.geekhunter.com.br"
        )
        self.login_url = f"{self.base_url}/candidates/sign_in"
        self.jobs_url = f"{self.base_url}/vagas"

        # Puxando credenciais do .env
        self.meu_email = os.getenv("GEEKHUNTER_EMAIL")
        self.minha_senha = os.getenv("GEEKHUNTER_PASSWORD")

        # Conexão com Redis
        host_redis = os.getenv(
            "REDIS_HOST", "localhost"
        )  # localhost para rodar no seu terminal, ou 'redis' no Docker
        try:
            self.redis_client = redis.Redis(
                host=host_redis, port=6379, db=0, decode_responses=True
            )
            self.redis_client.ping()
            logger.info("Conectado ao banco de dados Redis com sucesso!")
        except Exception as e:
            logger.warning(f"Não foi possível conectar ao Redis: {e}")

    def _gerar_id_unico(self, link):
        """Cria um ID único baseado no link da vaga para evitar duplicatas"""
        return hashlib.md5(link.encode("utf-8")).hexdigest()

    def _realizar_login(self, driver, wait):
        """Método interno para isolar a lógica de login"""
        logger.info("\n--- Verificando Autenticação ---")
        driver.get(self.login_url)
        try:
            email_fields = driver.find_elements(By.ID, "candidate_email")
            if email_fields:
                logger.info("Realizando login...")
                email_fields[0].send_keys(self.meu_email)
                driver.find_element(By.ID, "candidate_password").send_keys(
                    self.minha_senha
                )

                remember_me = driver.find_element(By.ID, "candidate_remember_me")
                driver.execute_script("arguments[0].click();", remember_me)
                driver.find_element(By.NAME, "commit").click()
                time.sleep(5)
            else:
                logger.info("Sessão ativa via cache.")
        except Exception as e:
            logger.error(f"Erro durante o login: {e}")

    def extrair_vagas(self, total_paginas=3):
        if not self.meu_email or not self.minha_senha:
            logger.error("Erro: Credenciais do GeekHunter não encontradas no .env")
            return

        chrome_options = Options()
        script_dir = os.path.dirname(os.path.abspath(__file__))
        user_data_dir = os.path.join(script_dir, "chrome_profile_gh")

        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
        chrome_options.add_argument("--start-maximized")
        # --- Configurações vitais para rodar no Docker ---
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        # -------------------------------------------------

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=chrome_options
        )
        wait = WebDriverWait(driver, 15)

        vagas_extraidas = []

        try:
            # 1. Autenticação
            self._realizar_login(driver, wait)

            # 2. Navegação para Vagas
            driver.get(self.jobs_url)
            time.sleep(5)

            # 3. Extração
            for pagina_atual in range(1, total_paginas + 1):
                logger.info(f"\n--- Processando Página {pagina_atual} ---")

                # Scroll para carregar a lista
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(3)
                driver.execute_script("window.scrollTo(0, 0);")

                cards = wait.until(
                    EC.presence_of_all_elements_located(
                        (By.CSS_SELECTOR, "a[aria-label='Visualizar vaga']")
                    )
                )

                links_vagas = []
                for card in cards:
                    try:
                        paragrafos = card.find_elements(By.TAG_NAME, "p")

                        titulo = (
                            paragrafos[0].text
                            if len(paragrafos) > 0
                            else "Título não encontrado"
                        )
                        tipo = (
                            paragrafos[1].text
                            if len(paragrafos) > 1
                            else "Não informado"
                        )
                        nivel = (
                            paragrafos[2].text
                            if len(paragrafos) > 2
                            else "Não informado"
                        )

                        links_vagas.append(
                            {
                                "titulo": titulo,
                                "link": card.get_attribute("href"),
                                "tipo": tipo,
                                "nivel": nivel,
                            }
                        )
                    except Exception as e:
                        logger.error(f"Opa! A estrutura do card mudou. Erro: {e}")
                        continue

                for i, v in enumerate(links_vagas, 1):
                    logger.info(f"  [{i}/{len(links_vagas)}] Abrindo: {v['titulo']}")

                    # Abre nova aba
                    driver.execute_script(
                        "window.open(arguments[0], '_blank');", v["link"]
                    )
                    driver.switch_to.window(driver.window_handles[1])

                    try:
                        time.sleep(2.5)
                        # Descrição
                        descricao = wait.until(
                            EC.presence_of_element_located(
                                (By.CLASS_NAME, "css-1htysii")
                            )
                        ).text

                        # --- EXTRAÇÃO REFINADA DE REGIME ---
                        regime = "Não informado"
                        for b in driver.find_elements(By.CLASS_NAME, "css-1szoa3k"):
                            txt = b.text.upper()
                            if "CLT" in txt or "PJ" in txt:
                                regime = b.text
                                break

                        # --- EXTRAÇÃO REFINADA DE SALÁRIO ---
                        salario = "Não informado"
                        precos = driver.find_elements(
                            By.XPATH,
                            "//p[contains(text(), 'R$')] | //p[contains(@class, 'css-149r4he')]",
                        )
                        if precos:
                            salario = precos[0].text

                        # --- O PADRÃO UNIVERSAL DE DADOS ---
                        link_vaga = v["link"]
                        id_unico = self._gerar_id_unico(link_vaga)

                        vaga_padronizada = {
                            "id_vaga": id_unico,
                            "plataforma": "GeekHunter",
                            "cargo_buscado": v["titulo"],  # O cargo base
                            "titulo": v["titulo"],
                            "empresa": "Confidencial",  # GeekHunter oculta a empresa na listagem padrão
                            "localizacao": "Não informado",
                            "modalidade": v["tipo"],  # Remoto, Híbrido, etc.
                            "regime": regime,
                            "salario": salario,
                            "descricao": descricao,
                            "link": link_vaga,
                        }

                    except Exception as e:
                        logger.error(f"Erro na captura de detalhes da vaga: {e}")
                        vaga_padronizada = None

                    # Fecha a aba e volta pra principal
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])

                    if vaga_padronizada:
                        vagas_extraidas.append(vaga_padronizada)
                        # Envia pro Redis (usando HSET para não duplicar vagas)
                        if hasattr(self, "redis_client"):
                            try:
                                self.redis_client.hset(
                                    "vagas_database",
                                    id_unico,
                                    json.dumps(vaga_padronizada),
                                )
                            except Exception as e:
                                pass

                # Paginação
                if pagina_atual < total_paginas:
                    try:
                        driver.execute_script(
                            "window.scrollTo(0, document.body.scrollHeight);"
                        )
                        time.sleep(2)
                        driver.execute_script(
                            "document.querySelectorAll('button.chakra-button')[document.querySelectorAll('button.chakra-button').length - 1].click();"
                        )
                    except Exception:
                        logger.info(
                            f"Fim da paginação alcançado na página {pagina_atual}."
                        )
                        break

            logger.info(
                f"\nSalvando {len(vagas_extraidas)} vagas no arquivo 'vagas_geekhunter.json' (Backup)..."
            )
            with open("vagas_geekhunter.json", "w", encoding="utf-8") as f:
                json.dump(vagas_extraidas, f, ensure_ascii=False, indent=4)
            logger.info("Extração do GeekHunter concluída com sucesso!")

            return vagas_extraidas

        except Exception as e:
            logger.error(f"Ocorreu um erro na execução do fluxo: {e}")

        finally:
            driver.quit()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    worker = GeekHunterWorker()
    worker.extrair_vagas(total_paginas=1)
