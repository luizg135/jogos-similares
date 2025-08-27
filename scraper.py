import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json
import requests
from bs4 import BeautifulSoup
import time

def get_sheet(sheet_name, client):
    """Abre e retorna uma aba específica da planilha."""
    try:
        spreadsheet = client.open_by_url(os.environ.get('GAME_SHEET_URL'))
        return spreadsheet.worksheet(sheet_name)
    except Exception as e:
        print(f"Erro ao abrir a aba '{sheet_name}': {e}")
        return None

def scrape_similar_games(game_name):
    """Faz o scraping de jogos similares para um único jogo."""
    print(f"--- Iniciando scraping para: {game_name} ---")
    slug = game_name.lower().replace(' ', '-').replace(':', '').replace("'", "")
    url = f"https://rawg.io/games/{slug}/suggested"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"AVISO: Falha ao acessar a página para '{game_name}'. Status: {response.status_code}")
            return []

        soup = BeautifulSoup(response.content, 'html.parser')
        cards = soup.find_all('div', class_='game-card')
        
        if not cards:
            print(f"INFO: Nenhum card de jogo similar encontrado para '{game_name}'.")
            return []

        similar_games_data = []
        for card in cards:
            title_element = card.find('a', class_='game-card-title')
            if not title_element: continue

            similar_name = title_element.text.strip()
            game_url = 'https://rawg.io' + title_element['href']
            
            metascore_div = card.find('div', class_='metacritic-score')
            metascore = metascore_div.text.strip() if metascore_div else 'N/A'
            
            platforms_div = card.find('div', class_='game-card-platforms')
            platforms = ', '.join([icon['class'][-1].replace('platform-icon--', '').upper() for icon in platforms_div.find_all('i')]) if platforms_div else 'N/A'
            
            similar_games_data.append([game_name, similar_name, platforms, metascore, game_url])
        
        print(f"SUCESSO: Encontrados {len(similar_games_data)} jogos similares para '{game_name}'.")
        return similar_games_data
    except Exception as e:
        print(f"ERRO CRÍTICO durante o scraping para '{game_name}': {e}")
        return []

def main():
    # Autenticação com o Google Sheets
    creds_json = json.loads(os.environ.get('GOOGLE_SHEETS_CREDENTIALS'))
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    client = gspread.authorize(creds)

    jogos_sheet = get_sheet('Jogos', client)
    similares_sheet = get_sheet('Jogos Similares', client)

    if not jogos_sheet or not similares_sheet:
        print("Não foi possível abrir as planilhas necessárias. Encerrando.")
        return

    # Verifica se a Action foi acionada com um nome de jogo específico
    single_game_name = os.environ.get('INPUT_GAME_NAME')
    
    games_to_scrape = []
    if single_game_name:
        print(f"Modo de execução: Jogo Único. Buscando por '{single_game_name}'.")
        games_to_scrape.append(single_game_name)
    else:
        print("Modo de execução: Completo. Buscando por todos os jogos na biblioteca.")
        all_games = jogos_sheet.col_values(1)[1:] # Pega todos os jogos da coluna A, exceto o cabeçalho
        games_to_scrape.extend(all_games)

    all_new_similar_games = []
    for game_name in games_to_scrape:
        if not game_name: continue
        
        # Faz o scraping
        similar_games = scrape_similar_games(game_name)
        all_new_similar_games.extend(similar_games)
        time.sleep(2) # Pausa para não sobrecarregar o servidor da RAWG

    if not all_new_similar_games:
        print("Nenhum novo jogo similar encontrado para adicionar.")
        return

    # Se estamos atualizando para um único jogo, removemos as entradas antigas dele
    if single_game_name:
        all_records = similares_sheet.get_all_values()
        rows_to_delete = [i + 1 for i, row in enumerate(all_records) if row and row[0] == single_game_name]
        for index in sorted(rows_to_delete, reverse=True):
            similares_sheet.delete_rows(index)
        print(f"Entradas antigas para '{single_game_name}' foram removidas.")
    else:
        # Se for a execução completa, limpa a planilha inteira
        similares_sheet.clear()
        similares_sheet.append_row(['Jogo Base', 'Jogo Similar', 'Plataformas', 'Metascore', 'URL'])
        print("Planilha 'Jogos Similares' foi limpa para a atualização completa.")

    # Adiciona os novos dados
    similares_sheet.append_rows(all_new_similar_games, value_input_option='USER_ENTERED')
    print(f"Total de {len(all_new_similar_games)} novas linhas de jogos similares foram adicionadas à planilha.")

if __name__ == "__main__":
    main()
