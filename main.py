import asyncio
import logging
from dotenv import load_dotenv

from Bots_Sites.bot_infojobs import InfoJobsWorker
from Bots_Sites.bot_linkedin import LinkedinWorker
from Bots_Sites.bot_geekhunter import GeekHunterWorker

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
load_dotenv()


async def worker_manager():
    logger.info("Iniciando o Orquestrador de Workers (Background Jobs)...")

    cargos_alvo = ["Desenvolvedor Backend Python", "Engenheiro de Software"]
    cidades_alvo = ["Remoto", "São Paulo"]

    infojobs_bot = InfoJobsWorker()
    linkedin_bot = LinkedinWorker()
    geekhunter_bot = GeekHunterWorker()

    logger.info("\n" + "=" * 50)
    logger.info("Disparando todas as esteiras de mineração SIMULTANEAMENTE...")

    # Preparamos as "tarefas"
    tarefa_infojobs = infojobs_bot.varrer_vagas(
        cargos_alvo, cidades_alvo, max_paginas=2
    )
    tarefa_linkedin = asyncio.to_thread(
        linkedin_bot.varrer_vagas, cargos_alvo, cidades_alvo, 2
    )
    tarefa_geekhunter = asyncio.to_thread(geekhunter_bot.extrair_vagas, 2)

    # O gather empacota tudo e manda rodar ao mesmo tempo.
    # O script só passa dessa linha quando TODOS os bots terminarem!
    try:
        await asyncio.gather(tarefa_infojobs, tarefa_linkedin, tarefa_geekhunter)
    except Exception as e:
        logger.error(f"Erro em uma das esteiras de processamento: {e}")

    logger.info("\n" + "=" * 50)
    logger.info("Todas as esteiras finalizaram com sucesso. Banco de dados atualizado!")


if __name__ == "__main__":
    asyncio.run(worker_manager())
