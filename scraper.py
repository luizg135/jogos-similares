import os
import json
import gspread
import asyncio
from playwright.async_api import async_playwright
from oauth2client.service_account import ServiceAccountCredentials
import re
import sys
import traceback

async def scrape_rawg_suggestions(game_title):
    """
    Navega na página de sugestões de um jogo, extraindo títulos, plataformas,
    Metascore, URLs e a IMAGEM da capa.
    """
    if game_title.lower() == 'forspoken':
        game_url_slug = 'project-athia'
        print("Tratamento especial para 'Forspoken': usando slug 'project-athia'.")
    else:
        game_url_slug = re.sub(r"[':]", '', game_title.lower())
        game_url_slug = re.sub(r'[\s]', '-', game_url_slug)
        game_url_slug = re.sub(r'[^a-z0-9-]', '', game_url_slug)
    
    url = f'https://rawg.io/games/{game_url_slug}/suggestions'
    print(f"URL de busca gerada: {url}")
    
    limit = 60
    browser = None # Inicializa browser como None
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            print(f"Buscando sugestões para '{game_title}' em: {url}")
            await page.goto(url, wait_until='domcontentloaded')

            await page.wait_for_selector('div.game-suggestions__items', timeout=60000)
            await page.wait_for_timeout(3000)
            
            last_height = await page.evaluate("document.body.scrollHeight")
            scroll_count = 0
            while True:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)
                new_height = await page.evaluate("document.body.scrollHeight")
                
                scroll_count += 1
                
                if new_height == last_height or len(await page.query_selector_all('div.game-card-large')) >= limit:
                    print(f"Rolagem finalizada após {scroll_count} iterações.")
                    break
                
                last_height = new_height

            game_elements = await page.query_selector_all('div.game-card-large')
            
            suggestions_list = []
            allowed_platforms = ['playstation', 'pc']
            
            for element in game_elements:
                try:
                    image_element = await element.query_selector('img.game-card-large__image')
                    image_url = await image_element.get_attribute('src') if image_element else ''
                    
                    platform_elements = await element.query_selector_all('div.platforms__platform')
                    platforms = []
                    for plat in platform_elements:
                        class_attr = await plat.get_attribute('class')
                        if class_attr:
                            platform_name = class_attr.split(' ')[-1].replace('platforms__platform_', '')
                            platforms.append(platform_name.lower())

                    metascore_element = await element.query_selector('div.metascore-label')
                    metascore = await metascore_element.inner_text() if metascore_element else 'N/A'
                    
                    if metascore == 'N/A' or not any(p in platforms for p in allowed_platforms):
                        continue
                        
                    link_element = await element.query_selector('a.game-card-compact__heading_with-link')
                    title = await link_element.inner_text()
                    url_suffix = await link_element.get_attribute('href')
                    
                    suggestions_list.append({
                        'title': title, 
                        'url': f"https://rawg.io{url_suffix}",
                        'platforms': ', '.join(p.upper() for p in platforms),
                        'metascore': metascore,
                        'image': image_url
                    })
                
                except Exception as e:
                    print(f"Erro ao extrair dados de um elemento: {e}")

            await browser.close()
            return suggestions_list[:limit]

    except Exception as e:
        print(f"Erro ao raspar a página de '{game_title}': {e}")
        if browser and browser.is_connected():
            await browser.close()
        return []

def get_google_sheets_client():
    credentials_json = os.environ.get('GOOGLE_CREDENTIALS')
    if not credentials_json:
        raise ValueError("GOOGLE_CREDENTIALS not found in environment variables.")
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        json.loads(credentials_json), 
        ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    )
    return gspread.authorize(creds)

def normalize_game_name(name):
    if not isinstance(name, str): return ""
    return re.sub(r"['\s:]", '', name.strip().lower())

async def main():
    game_to_process_from_arg = sys.argv[1] if len(sys.argv) > 1 else None
    
    try:
        client = get_google_sheets_client()
        spreadsheet = client.open("database-jogos")
        
        games_to_scrape = []

        if game_to_process_from_arg:
            print(f"Argumento recebido. Processando: '{game_to_process_from_arg}'")
            games_to_scrape.append(game_to_process_from_arg)
        else:
            print("Nenhum argumento. Verificando todos os jogos pendentes...")
            source_sheet = spreadsheet.worksheet("Jogos")
            all_game_titles = [cell[0] for cell in source_sheet.get_all_values() if cell and cell[0]]
            
            try:
                target_sheet = spreadsheet.worksheet("Jogos Similares")
                processed_titles_set = set(normalize_game_name(title) for title in target_sheet.col_values(1))
            except gspread.exceptions.WorksheetNotFound:
                target_sheet = spreadsheet.add_worksheet(title="Jogos Similares", rows="100", cols="6")
                processed_titles_set = set()
            
            games_to_scrape = [t for t in all_game_titles if normalize_game_name(t) not in processed_titles_set]

        if not games_to_scrape:
            print("Nenhum jogo para processar.")
            return
            
        print(f"Encontrados {len(games_to_scrape)} jogos para processar.")
        
        try:
            target_sheet = spreadsheet.worksheet("Jogos Similares")
        except gspread.exceptions.WorksheetNotFound:
            target_sheet = spreadsheet.add_worksheet(title="Jogos Similares", rows="100", cols="6")

        expected_header = ['Jogo Base', 'Jogo Similar', 'Plataformas', 'Metascore', 'URL', 'Imagem']
        current_header = target_sheet.row_values(1)
        if current_header != expected_header:
            target_sheet.update('A1:F1', [expected_header])
            print("Cabeçalho da planilha 'Jogos Similares' atualizado.")

        for game_title in games_to_scrape:
            suggestions = await scrape_rawg_suggestions(game_title)
            if suggestions:
                rows_to_append = [
                    [
                        game_title, s['title'], s['platforms'],
                        s['metascore'], s['url'], s['image']
                    ] for s in suggestions
                ]
                target_sheet.append_rows(rows_to_append)
                print(f"Dados de '{game_title}' salvos. {len(rows_to_append)} linhas adicionadas.")
            else:
                print(f"Nenhum resultado para '{game_title}'.")

    except Exception as e:
        print(f"Ocorreu um erro fatal: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())