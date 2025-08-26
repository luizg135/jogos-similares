import os
import json
import gspread
import asyncio
from playwright.async_api import async_playwright
from oauth2client.service_account import ServiceAccountCredentials
import re

async def scrape_rawg_suggestions(game_title):
    """
    Navega na página de sugestões de um jogo específico no RAWG.io,
    e retorna os títulos e URLs dos jogos sugeridos.
    """
    game_url_slug = game_title.lower()
    game_url_slug = re.sub(r'[\s\':]', '-', game_url_slug)
    game_url_slug = re.sub(r'[^a-z0-9-]', '', game_url_slug)
    
    url = f'https://rawg.io/games/{game_url_slug}/suggestions'

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print(f"Buscando sugestões para '{game_title}' em: {url}")
        await page.goto(url, wait_until='networkidle')

        try:
            await page.wait_for_selector('div.game-suggestions__items', timeout=60000)

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
        all_game_titles = [cell[0] for cell in source_sheet.get_all_values() if cell and cell[0] != '']
        
        if not all_game_titles:
            print("Nenhum título de jogo encontrado na planilha.")
            return

        # 3. Lógica para verificar jogos já processados
        try:
            target_sheet = spreadsheet.worksheet("Jogos Similares")
            processed_titles = target_sheet.col_values(1)
            processed_titles_set = set(processed_titles)
        except gspread.exceptions.WorksheetNotFound:
            print("Aba 'Jogos Similares' não encontrada. Criando...")
            target_sheet = spreadsheet.add_worksheet(title="Jogos Similares", rows="100", cols="4")
            target_sheet.update([['Jogo Base', 'Jogo Similar', 'URL']], 'A1:C1')
            processed_titles_set = set()

        # Filtra a lista para processar apenas jogos novos
        games_to_scrape = [
            title for title in all_game_titles if title not in processed_titles_set
        ]

        if not games_to_scrape:
            print("Todos os jogos já foram processados. Nenhuma ação necessária.")
            return
            
        print(f"Encontrados {len(games_to_scrape)} jogos para processar.")
        
        # Processa e salva cada jogo individualmente
        for game_title in games_to_scrape:
            suggestions = await scrape_rawg_suggestions(game_title)
            
            if suggestions:
                rows_to_append = []
                for suggestion in suggestions:
                    rows_to_append.append([game_title, suggestion['title'], suggestion['url']])
                
                target_sheet.append_rows(rows_to_append)
                print(f"Dados de '{game_title}' salvos com sucesso. {len(rows_to_append)} linhas adicionadas.")
            else:
                print(f"Nenhum resultado de jogos similares encontrado para '{game_title}'.")


    except Exception as e:
        print(f"Ocorreu um erro fatal: {e}")

if __name__ == "__main__":
    asyncio.run(main())
