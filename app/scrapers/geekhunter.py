import logging
import time
import os
import hashlib
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv
from app.core.database import SessionLocal, Vaga
from sqlalchemy.exc import IntegrityError
from selenium.webdriver.common.keys import Keys

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)


class GeekHunterWorker:
    def __init__(self):
        self.base_url = os.getenv("GEEKHUNTER_BASE_URL", "https://www.geekhunter.com.br")
        self.login_url = f"{self.base_url}/candidates/sign_in"
        self.jobs_url = f"{self.base_url}/vagas"
        self.my_email = os.getenv("GEEKHUNTER_EMAIL")
        self.my_password = os.getenv("GEEKHUNTER_PASSWORD")

    def _generate_unique_id(self, link):
        """Creates a unique ID based on the job link to avoid duplicates"""
        return hashlib.md5(link.encode("utf-8")).hexdigest()

    def _save_job(self, job_data):
        """Isolates the logic for saving data to the PostgreSQL database."""
        db = SessionLocal()
        try:
            new_job = Vaga(
                id_vaga_hash=job_data["id_vaga"],
                plataforma=job_data["plataforma"],
                cargo_buscado=job_data["cargo_buscado"],
                titulo=job_data["titulo"],
                empresa=job_data["empresa"],
                localizacao=job_data["localizacao"],
                modalidade=job_data["modalidade"],
                regime=job_data["regime"],
                salario=job_data["salario"],
                descricao=job_data["descricao"],
                link=job_data["link"]
            )
            db.add(new_job)
            db.commit()
            logger.info(f" Job saved in DB: {job_data['titulo']}")
            
        except IntegrityError:
            # If the job already exists in the database, silently ignore
            db.rollback()
            logger.info(f"Job already exists in DB, skipping: {job_data['titulo']}")
        except Exception as e:
            db.rollback()
            logger.error(f"Error saving job {job_data['titulo']} to Postgres: {e}")
        finally:
            db.close()

    def _perform_login(self, driver, wait):
        """Internal method to isolate login logic"""
        logger.info("\n--- Checking Authentication ---")
        driver.get(self.login_url)
        try:
            email_fields = driver.find_elements(By.ID, "candidate_email")
            if email_fields:
                logger.info("Logging in...")
                email_fields[0].send_keys(self.my_email)
                
                # Pegamos o campo de senha
                password_field = driver.find_element(By.ID, "candidate_password")
                password_field.send_keys(self.my_password)

                # Marca o "Lembrar de mim"
                remember_me = driver.find_element(By.ID, "candidate_remember_me")
                driver.execute_script("arguments[0].click();", remember_me)
                
                password_field.send_keys(Keys.RETURN)
                
                time.sleep(5)
            else:
                logger.info("Active session found via cache.")
        except Exception as e:
            logger.error(f"Error during login: {e}")

    def extract_jobs(self, total_pages=2):
        if not self.my_email or not self.my_password:
            logger.error("Error: GeekHunter credentials not found in .env")
            return

        chrome_options = Options()
        script_dir = os.path.dirname(os.path.abspath(__file__))
        user_data_dir = os.path.join(script_dir, "chrome_profile_gh")

        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=chrome_options
        )
        wait = WebDriverWait(driver, 15)

        try:
            # Authentication
            self._perform_login(driver, wait)

            # Navigate to Jobs
            driver.get(self.jobs_url)
            time.sleep(5)

            # Extraction Loop
            for current_page in range(1, total_pages + 1):
                logger.info(f"\n--- Processing Page {current_page} ---")

                # Scroll to load the list
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(3)
                driver.execute_script("window.scrollTo(0, 0);")

                cards = wait.until(
                    EC.presence_of_all_elements_located(
                        (By.CSS_SELECTOR, "a[aria-label='Visualizar vaga']")
                    )
                )

                job_links = []
                for card in cards:
                    try:
                        paragraphs = card.find_elements(By.TAG_NAME, "p")
                        titulo = paragraphs[0].text if len(paragraphs) > 0 else "Title not found"
                        tipo = paragraphs[1].text if len(paragraphs) > 1 else "Not informed"
                        nivel = paragraphs[2].text if len(paragraphs) > 2 else "Not informed"

                        job_links.append({
                            "titulo": titulo,
                            "link": card.get_attribute("href"),
                            "tipo": tipo,
                            "nivel": nivel,
                        })
                    except Exception as e:
                        logger.error(f"Card structure changed. Error: {e}")
                        continue

                for i, v in enumerate(job_links, 1):
                    logger.info(f"  [{i}/{len(job_links)}] Opening: {v['titulo']}")

                    # Open new tab
                    driver.execute_script("window.open(arguments[0], '_blank');", v["link"])
                    driver.switch_to.window(driver.window_handles[1])

                    try:
                        time.sleep(2.5)
                        
                        # Description
                        descricao = wait.until(
                            EC.presence_of_element_located((By.CLASS_NAME, "css-1htysii"))
                        ).text

                        # Regime
                        regime = "Not informed"
                        for b in driver.find_elements(By.CLASS_NAME, "css-1szoa3k"):
                            txt = b.text.upper()
                            if "CLT" in txt or "PJ" in txt:
                                regime = b.text
                                break

                        # Salary
                        salario = "Not informed"
                        prices = driver.find_elements(
                            By.XPATH,
                            "//p[contains(text(), 'R$')] | //p[contains(@class, 'css-149r4he')]",
                        )
                        if prices:
                            salario = prices[0].text

                        link_vaga = v["link"]
                        id_unico = self._generate_unique_id(link_vaga)

                        standardized_job = {
                            "id_vaga": id_unico,
                            "plataforma": "GeekHunter",
                            "cargo_buscado": v["titulo"], 
                            "titulo": v["titulo"],
                            "empresa": "Confidencial", 
                            "localizacao": "Não informado",
                            "modalidade": v["tipo"], 
                            "regime": regime,
                            "salario": salario,
                            "descricao": descricao,
                            "link": link_vaga,
                        }
                        
                        self._save_job(standardized_job)

                    except Exception as e:
                        logger.error(f"Error capturing job details: {e}")

                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])

                if current_page < total_pages:
                    try:
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        time.sleep(2)
                        driver.execute_script(
                            "document.querySelectorAll('button.chakra-button')[document.querySelectorAll('button.chakra-button').length - 1].click();"
                        )
                    except Exception:
                        logger.info(f"End of pagination reached at page {current_page}.")
                        break

            logger.info("GeekHunter extraction finished successfully!")

        except Exception as e:
            logger.error(f"An error occurred during execution: {e}")

        finally:
            driver.quit()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    worker = GeekHunterWorker()
    worker.extract_jobs(total_pages=1)