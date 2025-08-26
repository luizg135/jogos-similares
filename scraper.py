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
    e retorna até 30 títulos, plataformas, Metascore e URLs de jogos sugeridos.
    """
    # --- LÓGICA CORRIGIDA PARA TRATAR NOMES DE JOGOS ---
    # 1. Converte para minúsculas.
    # 2. Remove apóstrofos e dois-pontos.
    # 3. Substitui espaços por hífens.
    # 4. Remove quaisquer outros caracteres não alfanuméricos ou hífens.
    game_url_slug = re.sub(r"[':]", '', game_title.lower())
    game_url_slug = re.sub(r'[\s]', '-', game_url_slug)
    game_url_slug = re.sub(r'[^a-z0-9-]', '', game_url_slug)
    
    url = f'https://rawg.io/games/{game_url_slug}/suggestions'
    print(f"URL de busca gerada: {url}")
    
    limit = 30
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print(f"Buscando sugestões para '{game_title}' em: {url}")
        await page.goto(url, wait_until='domcontentloaded')

        try:
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
                    print(f"Rolagem finalizada após {scroll_count} iterações. Total de jogos carregados.")
                    break
                
                last_height = new_height

            game_elements = await page.query_selector_all('div.game-card-large')
            
            suggestions_list = []
            allowed_platforms = ['playstation', 'pc']
            
            for element in game_elements:
                try:
                    platform_elements = await element.query_selector_all('div.platforms__platform')
                    platforms = []
                    for p in platform_elements:
                        class_attr = await p.get_attribute('class')
                        if class_attr:
                            platform_name = class_attr.split(' ')[-1].replace('platforms__platform_', '')
                            platforms.append(platform_name.lower())
                    
                    metascore_element = await element.query_selector('div.metascore-label')
                    metascore = await metascore_element.inner_text() if metascore_element else 'N/A'
                    
                    if metascore == 'N/A':
                        print(f"Jogo ignorado por ter Metascore 'N/A'.")
                        continue

                    if not any(p in platforms for p in allowed_platforms):
                        print("Jogo ignorado por não estar em PC ou PlayStation.")
                        continue
                        
                    link_element = await element.query_selector('a.game-card-compact__heading_with-link')
                    title = await link_element.inner_text()
                    url_suffix = await link_element.get_attribute('href')
                    
                    suggestions_list.append({
                        'title': title, 
                        'url': f"https://rawg.io{url_suffix}",
                        'platforms': ', '.join(p.upper() for p in platforms),
                        'metascore': metascore
                    })
                
                except Exception as e:
                    print(f"Erro ao extrair dados de um elemento: {e}")

            await browser.close()
            return suggestions_list[:limit]

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

def normalize_game_name(name):
    """Converte o nome do jogo para minúsculas e remove caracteres especiais para comparação."""
    if not isinstance(name, str):
        return ""
    name = name.strip().lower()
    return re.sub(r"['\s:]", '', name)

async def main():
    """
    Função principal que orquestra a leitura, raspagem e escrita dos dados.
    """
    try:
        client = get_google_sheets_client()
        spreadsheet_name = "database-jogos"
        spreadsheet = client.open(spreadsheet_name)
        
        source_sheet = spreadsheet.worksheet("Jogos")
        all_game_titles = [cell[0] for cell in source_sheet.get_all_values() if cell and cell[0] != '']
        
        if not all_game_titles:
            print("Nenhum título de jogo encontrado na planilha.")
            return

        try:
            target_sheet = spreadsheet.worksheet("Jogos Similares")
            processed_titles = [normalize_game_name(title) for title in target_sheet.col_values(1)]
            processed_titles_set = set(processed_titles)
        except gspread.exceptions.WorksheetNotFound:
            print("Aba 'Jogos Similares' não encontrada. Criando...")
            target_sheet = spreadsheet.add_worksheet(title="Jogos Similares", rows="100", cols="4")
            target_sheet.update([['Jogo Base', 'Jogo Similar', 'Plataformas', 'Metascore', 'URL']], 'A1:E1')
            processed_titles_set = set()

        games_to_scrape = [
            title for title in all_game_titles if normalize_game_name(title) not in processed_titles_set
        ]

        if not games_to_scrape:
            print("Todos os jogos já foram processados. Nenhuma ação necessária.")
            return
            
        print(f"Encontrados {len(games_to_scrape)} jogos para processar.")
        
        for game_title in games_to_scrape:
            suggestions = await scrape_rawg_suggestions(game_title)
            
            if suggestions:
                rows_to_append = []
                for suggestion in suggestions:
                    rows_to_append.append([
                        game_title,
                        suggestion['title'],
                        suggestion['platforms'],
                        suggestion['metascore'],
                        suggestion['url']
                    ])
                
                target_sheet.append_rows(rows_to_append)
                print(f"Dados de '{game_title}' salvos com sucesso. {len(rows_to_append)} linhas adicionadas.")
            else:
                print(f"Nenhum resultado de jogos similares encontrado para '{game_title}'.")

    except Exception as e:
        print(f"Ocorreu um erro fatal: {e}")

if __name__ == "__main__":
    asyncio.run(main())
