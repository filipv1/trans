from flask import Flask, jsonify, request, render_template_string
import os
import json
from datetime import datetime
import requests
import pandas as pd
from typing import Dict, List, Optional

app = Flask(__name__)

# HTML template pro základní UI
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Trans.eu Arbitráž Detektor</title>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { text-align: center; margin-bottom: 30px; }
        .button { background: #007bff; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; margin: 10px; }
        .button:hover { background: #0056b3; }
        .results { margin-top: 30px; }
        .table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        .table th, .table td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        .table th { background-color: #f2f2f2; }
        .status { padding: 20px; margin: 20px 0; border-radius: 5px; }
        .success { background-color: #d4edda; color: #155724; }
        .error { background-color: #f8d7da; color: #721c24; }
        .info { background-color: #d1ecf1; color: #0c5460; }
        .loading { text-align: center; padding: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚛 Trans.eu Arbitráž Detektor</h1>
            <p>Detekce arbitrážních příležitostí v logistickém marketplacu</p>
        </div>
        
        <div>
            <button class="button" onclick="runAnalysis()">🔍 Spustit analýzu</button>
            <button class="button" onclick="getFreights()">📊 Získat nabídky</button>
            <button class="button" onclick="checkStatus()">⚡ Status API</button>
        </div>
        
        <div id="results" class="results"></div>
    </div>

    <script>
        async function apiCall(endpoint, method = 'GET', data = null) {
            const options = {
                method: method,
                headers: { 'Content-Type': 'application/json' }
            };
            
            if (data) {
                options.body = JSON.stringify(data);
            }
            
            try {
                const response = await fetch(endpoint, options);
                return await response.json();
            } catch (error) {
                return { error: error.message };
            }
        }
        
        async function runAnalysis() {
            document.getElementById('results').innerHTML = '<div class="loading">🔄 Spouštím analýzu...</div>';
            
            const result = await apiCall('/api/analyze');
            displayResults('Výsledky analýzy', result);
        }
        
        async function getFreights() {
            document.getElementById('results').innerHTML = '<div class="loading">📊 Získávám nabídky...</div>';
            
            const result = await apiCall('/api/freights');
            displayResults('Freight nabídky', result);
        }
        
        async function checkStatus() {
            const result = await apiCall('/api/status');
            displayResults('Status API', result);
        }
        
        function displayResults(title, data) {
            let html = `<h2>${title}</h2>`;
            
            if (data.error) {
                html += `<div class="status error">❌ Chyba: ${data.error}</div>`;
            } else if (data.success === false) {
                html += `<div class="status error">❌ ${data.message || 'Operace selhala'}</div>`;
            } else {
                html += `<div class="status success">✅ Operace úspěšná</div>`;
                
                if (data.summary) {
                    html += '<h3>Souhrn:</h3><ul>';
                    for (const [key, value] of Object.entries(data.summary)) {
                        html += `<li><strong>${key}:</strong> ${value}</li>`;
                    }
                    html += '</ul>';
                }
                
                if (data.arbitrage_opportunities && data.arbitrage_opportunities.length > 0) {
                    html += '<h3>🎯 Arbitrážní příležitosti:</h3>';
                    html += '<table class="table"><tr><th>Trasa</th><th>Volatilita</th><th>Min cena</th><th>Max cena</th><th>Počet nabídek</th></tr>';
                    
                    data.arbitrage_opportunities.forEach(opp => {
                        html += `<tr>
                            <td>${opp.route}</td>
                            <td>${(opp.price_volatility * 100).toFixed(1)}%</td>
                            <td>${opp.price_min} EUR</td>
                            <td>${opp.price_max} EUR</td>
                            <td>${opp.price_count}</td>
                        </tr>`;
                    });
                    html += '</table>';
                }
                
                if (data.freights && data.freights.length > 0) {
                    html += `<h3>📦 Nabídky přepravy (${data.freights.length}):</h3>`;
                    html += '<table class="table"><tr><th>ID</th><th>Trasa</th><th>Cena</th><th>Kapacita</th><th>Status</th></tr>';
                    
                    data.freights.slice(0, 10).forEach(freight => {
                        html += `<tr>
                            <td>${freight.freight_id}</td>
                            <td>${freight.loading_city} → ${freight.unloading_city}</td>
                            <td>${freight.price} ${freight.currency}</td>
                            <td>${freight.capacity} ${freight.capacity_unit}</td>
                            <td>${freight.status}</td>
                        </tr>`;
                    });
                    html += '</table>';
                    
                    if (data.freights.length > 10) {
                        html += `<p><em>... a dalších ${data.freights.length - 10} nabídek</em></p>`;
                    }
                }
            }
            
            document.getElementById('results').innerHTML = html;
        }
    </script>
</body>
</html>
"""

class TransEuAPIClient:
    """Trans.eu API Client pro Flask aplikaci"""
    
    def __init__(self):
        # Získání credentials z environment variables
        self.api_key = os.getenv('TRANSEU_API_KEY')
        self.client_id = os.getenv('TRANSEU_CLIENT_ID') 
        self.client_secret = os.getenv('TRANSEU_CLIENT_SECRET')
        self.base_url = "https://api.platform.trans.eu"
        self.access_token = None
        self.token_expires_at = None
        
    def is_configured(self) -> bool:
        """Kontrola, zda jsou nastaveny potřebné credentials"""
        return all([self.api_key, self.client_id, self.client_secret])
    
    def get_access_token(self) -> str:
        """Získání OAuth2 access tokenu"""
        if self.access_token and self.token_expires_at and datetime.now() < self.token_expires_at:
            return self.access_token
            
        auth_url = f"{self.base_url}/oauth/v2/token"
        
        data = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }
        
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        
        response = requests.post(auth_url, data=data, headers=headers)
        response.raise_for_status()
        
        token_data = response.json()
        self.access_token = token_data['access_token']
        
        # Nastavení času expirace
        expires_in = token_data.get('expires_in', 3600)
        from datetime import timedelta
        self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 60)
        
        return self.access_token
    
    def get_headers(self) -> Dict[str, str]:
        """Vytvoření headers pro API requesty"""
        return {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.get_access_token()}',
            'Api-key': self.api_key
        }
    
    def get_freight_proposals(self, limit: int = 50) -> List[Dict]:
        """Získání freight proposals"""
        endpoint = "/ext/freights-api/v1/freight-proposals"
        url = f"{self.base_url}{endpoint}"
        
        params = {
            'sortBy': 'loading_date',
            'order': 'ASC',
            'limit': limit,
            'filter': json.dumps({
                "is_archived": False,
                "proposal_request_status": "published"
            })
        }
        
        response = requests.get(url, headers=self.get_headers(), params=params)
        response.raise_for_status()
        
        data = response.json()
        return data if isinstance(data, list) else []
    
    def extract_freight_data(self, proposals: List[Dict]) -> List[Dict]:
        """Extrakce klíčových dat z freight proposals"""
        freight_data = []
        
        for proposal in proposals:
            try:
                freight = proposal.get('freight', {})
                
                # Základní informace
                freight_id = freight.get('id')
                status = proposal.get('status')
                
                # Cenové informace
                publication = freight.get('publication', {})
                price_info = publication.get('price', {})
                price = price_info.get('value', 0)
                currency = price_info.get('currency', 'EUR')
                
                # Informace o kapacitě
                capacity_info = freight.get('capacity', {})
                capacity = capacity_info.get('value', 0)
                capacity_unit = capacity_info.get('unit_code', 't')
                
                # Informace o trasách
                spots = freight.get('spots', [])
                if len(spots) >= 2:
                    # Nakládka
                    loading_spot = spots[0]
                    loading_address = loading_spot.get('place', {}).get('address', {})
                    loading_country = loading_address.get('country', '').upper()
                    loading_city = loading_address.get('locality', '')
                    
                    # Vykládka
                    unloading_spot = spots[-1]
                    unloading_address = unloading_spot.get('place', {}).get('address', {})
                    unloading_country = unloading_address.get('country', '').upper()
                    unloading_city = unloading_address.get('locality', '')
                    
                    freight_record = {
                        'freight_id': freight_id,
                        'status': status,
                        'price': price,
                        'currency': currency,
                        'capacity': capacity,
                        'capacity_unit': capacity_unit,
                        'loading_country': loading_country,
                        'loading_city': loading_city,
                        'unloading_country': unloading_country,
                        'unloading_city': unloading_city,
                        'route': f"{loading_country}-{unloading_country}",
                        'distance_km': freight.get('distance', 0)
                    }
                    
                    freight_data.append(freight_record)
                    
            except Exception as e:
                print(f"Chyba při zpracování freight {freight.get('id', 'unknown')}: {e}")
                continue
        
        return freight_data
    
    def detect_arbitrage_opportunities(self, freight_data: List[Dict]) -> List[Dict]:
        """Detekce arbitrážních příležitostí"""
        if not freight_data:
            return []
        
        df = pd.DataFrame(freight_data)
        
        # Analýza podle tras
        route_analysis = df.groupby('route').agg({
            'price': ['mean', 'min', 'max', 'count']
        }).round(2)
        
        route_analysis.columns = ['price_mean', 'price_min', 'price_max', 'price_count']
        route_analysis.reset_index(inplace=True)
        
        # Výpočet volatility
        route_analysis['price_volatility'] = (
            (route_analysis['price_max'] - route_analysis['price_min']) / 
            route_analysis['price_mean'].replace(0, 1)
        ).round(3)
        
        # Filtrace tras s vysokou volatilitou
        arbitrage_routes = route_analysis[
            (route_analysis['price_volatility'] > 0.2) & 
            (route_analysis['price_count'] >= 2)
        ].sort_values('price_volatility', ascending=False)
        
        return arbitrage_routes.to_dict('records')


# Inicializace API clienta
api_client = TransEuAPIClient()

@app.route('/api/freights')
def get_freights():
    """Získání freight proposals"""
    try:
        if not api_client.is_configured():
            return jsonify({
                'success': False,
                'message': 'API credentials nejsou nastaveny'
            })
        
        # Získání dat
        proposals = api_client.get_freight_proposals(limit=100)
        freight_data = api_client.extract_freight_data(proposals)
        
        return jsonify({
            'success': True,
            'message': f'Získáno {len(freight_data)} nabídek',
            'freights': freight_data[:20],  # Omezení pro rychlost
            'total_count': len(freight_data),
            'summary': {
                'Celkem nabídek': len(freight_data),
                'Unikátních tras': len(set(f['route'] for f in freight_data)),
                'Průměrná cena': round(sum(f['price'] for f in freight_data) / len(freight_data), 2) if freight_data else 0
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Chyba při získávání dat: {str(e)}'
        })

@app.route('/api/analyze')
def analyze_arbitrage():
    """Spuštění analýzy arbitráže"""
    try:
        if not api_client.is_configured():
            return jsonify({
                'success': False,
                'message': 'API credentials nejsou nastaveny'
            })
        
        # Získání dat
        proposals = api_client.get_freight_proposals(limit=200)
        freight_data = api_client.extract_freight_data(proposals)
        
        if not freight_data:
            return jsonify({
                'success': False,
                'message': 'Nepodařilo se získat žádná data pro analýzu'
            })
        
        # Detekce arbitráže
        arbitrage_opportunities = api_client.detect_arbitrage_opportunities(freight_data)
        
        return jsonify({
            'success': True,
            'message': f'Analýza dokončena. Nalezeno {len(arbitrage_opportunities)} arbitrážních příležitostí.',
            'summary': {
                'Celkem nabídek': len(freight_data),
                'Unikátních tras': len(set(f['route'] for f in freight_data)),
                'Arbitrážních příležitostí': len(arbitrage_opportunities),
                'Průměrná volatilita': round(sum(opp['price_volatility'] for opp in arbitrage_opportunities) / len(arbitrage_opportunities), 3) if arbitrage_opportunities else 0
            },
            'arbitrage_opportunities': arbitrage_opportunities[:10],  # Top 10
            'freights': freight_data[:10]  # Ukázka dat
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Chyba při analýze: {str(e)}'
        })

@app.route('/api/route/<route_code>')
def get_route_details(route_code):
    """Detail konkrétní trasy"""
    try:
        if not api_client.is_configured():
            return jsonify({
                'success': False,
                'message': 'API credentials nejsou nastaveny'
            })
        
        # Získání dat
        proposals = api_client.get_freight_proposals(limit=500)
        freight_data = api_client.extract_freight_data(proposals)
        
        # Filtrace podle trasy
        route_freights = [f for f in freight_data if f['route'] == route_code.upper()]
        
        if not route_freights:
            return jsonify({
                'success': False,
                'message': f'Nenalezeny žádné nabídky pro trasu {route_code}'
            })
        
        # Statistiky trasy
        prices = [f['price'] for f in route_freights]
        
        return jsonify({
            'success': True,
            'route': route_code.upper(),
            'freights': route_freights,
            'statistics': {
                'count': len(route_freights),
                'min_price': min(prices),
                'max_price': max(prices),
                'avg_price': round(sum(prices) / len(prices), 2),
                'price_spread': max(prices) - min(prices),
                'volatility': round((max(prices) - min(prices)) / (sum(prices) / len(prices)), 3)
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Chyba při získávání detailů trasy: {str(e)}'
        })

@app.route('/health')
def health_check():
    """Health check pro Railway"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'Trans.eu Arbitrage Detector'
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)app.route('/')
def index():
    """Hlavní stránka s UI"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/status')
def api_status():
    """Kontrola stavu API"""
    try:
        if not api_client.is_configured():
            return jsonify({
                'success': False,
                'message': 'API credentials nejsou nastaveny. Zkontrolujte environment variables.',
                'required_vars': ['TRANSEU_API_KEY', 'TRANSEU_CLIENT_ID', 'TRANSEU_CLIENT_SECRET']
            })
        
        # Test API připojení
        token = api_client.get_access_token()
        
        return jsonify({
            'success': True,
            'message': 'API je připraveno k použití',
            'has_token': bool(token),
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Chyba API: {str(e)}'
        })

@
