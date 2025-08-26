import os
import json
import gspread
import asyncio
from playwright.async_api import async_playwright
from oauth2client.service_account import ServiceAccountCredentials

async def scrape_rawg_suggestions(game_title):
    """
    Navega na página de sugestões de um jogo específico no RAWG.io,
    e retorna os títulos e URLs dos jogos sugeridos.
    """
    game_url_slug = game_title.lower().replace(' ', '-')
    url = f'https://rawg.io/games/{game_url_slug}/suggestions'

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print(f"Buscando sugestões para '{game_title}' em: {url}")
        await page.goto(url, wait_until='networkidle')

        try:
            # Espera que o contêiner principal dos jogos esteja visível
            await page.wait_for_selector('div.game-suggestions__items', timeout=60000)

            # Encontra todos os elementos de cartão de jogo
            game_elements = await page.query_selector_all('div.game-card-large')
            
            suggestions_list = []
            for element in game_elements:
                link_element = await element.query_selector('a.game-card-compact__heading_with-link')
                if link_element:
                    title = await link_element.inner_text()
                    url_suffix = await link_element.get_attribute('href')
                    suggestions_list.append({
                        'title': title, 
                        'url': f"https://rawg.io{url_suffix}"
                    })

            await browser.close()
            return suggestions_list

        except Exception as e:
            print(f"Erro ao raspar a página de '{game_title}': {e}")
            await browser.close()
            return []

def get_google_sheets_client():
    """
    Cria um cliente gspread para interagir com o Google Sheets,
    usando credenciais do GitHub Secrets.
    """
    credentials_json = os.environ.get('GOOGLE_CREDENTIALS')
    if not credentials_json:
        raise ValueError("GOOGLE_CREDENTIALS not found in environment variables.")
        
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        json.loads(credentials_json), 
        ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    )
    return gspread.authorize(creds)

async def main():
    """
    Função principal que orquestra a leitura, raspagem e escrita dos dados.
    """
    try:
        # 1. Autentica e acessa a planilha
        client = get_google_sheets_client()
        spreadsheet_name = "database-jogos"
        spreadsheet = client.open(spreadsheet_name)
        
        # 2. Lê a coluna A da aba 'Jogos'
        source_sheet = spreadsheet.worksheet("Jogos")
        game_titles = [cell[0] for cell in source_sheet.get_all_values() if cell and cell[0] != '']
        
        if not game_titles:
            print("Nenhum título de jogo encontrado na planilha.")
            return

        # 3. Prepara a aba 'Jogos Similares' para escrever
        try:
            target_sheet = spreadsheet.worksheet("Jogos Similares")
            # Limpa o conteúdo da aba antes de escrever
            target_sheet.clear()
        except gspread.exceptions.WorksheetNotFound:
            print("Criando a aba 'Jogos Similares'...")
            target_sheet = spreadsheet.add_worksheet(title="Jogos Similares", rows="100", cols="4")

        # Escreve o cabeçalho
        target_sheet.update('A1:C1', [['Jogo Base', 'Jogo Similar', 'URL']])
        
        all_results = []
        for game_title in game_titles:
            print(f"Processando jogo: {game_title}")
            suggestions = await scrape_rawg_suggestions(game_title)
            
            for suggestion in suggestions:
                all_results.append([game_title, suggestion['title'], suggestion['url']])

        # 4. Salva os resultados
        if all_results:
            target_sheet.append_rows(all_results)
            print(f"Dados salvos com sucesso na aba 'Jogos Similares'. {len(all_results)} linhas adicionadas.")
        else:
            print("Nenhum resultado de jogos similares encontrado.")

    except Exception as e:
        print(f"Ocorreu um erro fatal: {e}")

if __name__ == "__main__":
    asyncio.run(main())
