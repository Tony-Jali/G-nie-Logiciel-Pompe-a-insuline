import network
import socket
import time
from machine import Pin, ADC

# Configuration WiFi
SSID = "iPhone tony"
PASSWORD = "Tony 237"

# Configuration matérielle
led = Pin(2, Pin.OUT)
potentiometre = ADC(Pin(34))  # GPIO 34 pour le potentiomètre
potentiometre.atten(ADC.ATTN_11DB)  # Plage 0-3.3V
potentiometre.width(ADC.WIDTH_12BIT)  # Résolution 12 bits (0-4095)

# Variables globales
current_glucose = 0
readings_history = []
last_stable_value = 0
readings_buffer = []
STABILITY_THRESHOLD = 5  # Seuil de variation acceptable en mg/dL

def connect_wifi():
    """Se connecte au WiFi"""
    print("🔧 Configuration WiFi...")
    
    ap = network.WLAN(network.AP_IF)
    ap.active(False)
    
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    time.sleep(1)
    
    if wlan.isconnected():
        config = wlan.ifconfig()
        print(f"✅ Déjà connecté!")
        print(f"📡 IP: {config[0]}")
        led.on()
        return wlan
    
    print(f"🔄 Connexion à '{SSID}'...")
    wlan.connect(SSID, PASSWORD)
    
    max_wait = 20
    while max_wait > 0:
        if wlan.isconnected():
            config = wlan.ifconfig()
            print(f"✅ CONNECTÉ!")
            print(f"📡 IP: {config[0]}")
            print(f"🌐 URL: http://{config[0]}")
            led.on()
            return wlan
        
        print(".", end="")
        led.value(not led.value())
        time.sleep(1)
        max_wait -= 1
    
    print(f"\n❌ Timeout")
    return None

def read_glucose():
    """Lit le potentiomètre et convertit en taux de glycémie (mg/dL) avec filtrage"""
    global current_glucose, last_stable_value, readings_buffer
    
    # Faire plusieurs lectures pour moyenner (réduire le bruit)
    samples = []
    for _ in range(10):
        adc_value = potentiometre.read()
        samples.append(adc_value)
        time.sleep_ms(5)
    
    # Moyenne des lectures
    avg_adc = sum(samples) // len(samples)
    
    # Convertir en glycémie: 20 mg/dL à 400 mg/dL
    glucose = int((avg_adc / 4095) * 380 + 20)
    
    # Arrondir à la dizaine la plus proche pour stabiliser
    glucose = round(glucose / 10) * 10
    
    # Appliquer un filtre de stabilité
    if abs(glucose - last_stable_value) < STABILITY_THRESHOLD:
        # Si la variation est minime, garder la valeur précédente
        glucose = last_stable_value
    else:
        # Sinon, mettre à jour la valeur stable
        last_stable_value = glucose
    
    current_glucose = glucose
    return glucose

def get_glucose_status(glucose):
    """Détermine le statut de la glycémie"""
    if glucose < 70:
        return "HYPOGLYCÉMIE", "#ef4444", "⚠️"
    elif glucose <= 140:
        return "NORMAL", "#10b981", "✅"
    elif glucose <= 200:
        return "ÉLEVÉ", "#f59e0b", "⚡"
    else:
        return "HYPERGLYCÉMIE", "#dc2626", "🚨"

def web_page():
    """Génère la page HTML avec graphique temps réel"""
    glucose = read_glucose()
    status, color, icon = get_glucose_status(glucose)
    uptime = time.ticks_ms() // 1000
    
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Glucomètre ESP32</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        
        .container {{
            max-width: 600px;
            margin: 0 auto;
        }}
        
        .card {{
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            padding: 30px;
            margin-bottom: 20px;
        }}
        
        h1 {{
            color: #1e3c72;
            text-align: center;
            margin-bottom: 10px;
            font-size: 2em;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
        }}
        
        .subtitle {{
            text-align: center;
            color: #666;
            margin-bottom: 30px;
            font-size: 0.9em;
        }}
        
        .main-display {{
            text-align: center;
            padding: 40px 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 15px;
            color: white;
            margin-bottom: 20px;
        }}
        
        .glucose-value {{
            font-size: 4.5em;
            font-weight: bold;
            line-height: 1;
            margin: 10px 0;
        }}
        
        .glucose-unit {{
            font-size: 1.2em;
            opacity: 0.9;
            margin-bottom: 15px;
        }}
        
        .status-badge {{
            display: inline-block;
            padding: 10px 25px;
            border-radius: 25px;
            font-weight: bold;
            font-size: 1.1em;
            background: rgba(255,255,255,0.3);
            margin-top: 10px;
        }}
        
        .chart-container {{
            background: #f8f9fa;
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            height: 250px;
            position: relative;
        }}
        
        canvas {{
            width: 100% !important;
            height: 100% !important;
        }}
        
        .info-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
            margin-bottom: 20px;
        }}
        
        .info-item {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 10px;
            text-align: center;
        }}
        
        .info-label {{
            font-size: 0.85em;
            color: #666;
            margin-bottom: 5px;
        }}
        
        .info-value {{
            font-size: 1.3em;
            font-weight: bold;
            color: #333;
        }}
        
        .reference-table {{
            background: #f8f9fa;
            border-radius: 10px;
            padding: 15px;
            font-size: 0.9em;
        }}
        
        .reference-table h3 {{
            color: #333;
            margin-bottom: 10px;
            font-size: 1em;
        }}
        
        .ref-row {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #e0e0e0;
        }}
        
        .ref-row:last-child {{
            border-bottom: none;
        }}
        
        .ref-indicator {{
            width: 15px;
            height: 15px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 8px;
        }}
        
        .loading {{
            text-align: center;
            color: #666;
            padding: 20px;
            font-size: 0.9em;
        }}
        
        @keyframes pulse {{
            0%, 100% {{ transform: scale(1); }}
            50% {{ transform: scale(1.05); }}
        }}
        
        .pulse {{
            animation: pulse 2s infinite;
        }}
        
        @media (max-width: 480px) {{
            .card {{
                padding: 20px;
            }}
            .glucose-value {{
                font-size: 3.5em;
            }}
            .info-grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <h1>🩸 Glucomètre ESP32</h1>
            <p class="subtitle">Simulation en temps réel</p>
            
            <div class="main-display pulse">
                <div class="glucose-value">{glucose}</div>
                <div class="glucose-unit">mg/dL</div>
                <div class="status-badge">{icon} {status}</div>
            </div>
            
            <div class="chart-container">
                <canvas id="glucoseChart"></canvas>
            </div>
            
            <div class="info-grid">
                <div class="info-item">
                    <div class="info-label">📊 Mesures</div>
                    <div class="info-value" id="measureCount">0</div>
                </div>
                <div class="info-item">
                    <div class="info-label">⏱️ Dernière mesure</div>
                    <div class="info-value" id="lastUpdate">0s</div>
                </div>
                <div class="info-item">
                    <div class="info-label">📉 Minimum</div>
                    <div class="info-value" id="minValue">--</div>
                </div>
                <div class="info-item">
                    <div class="info-label">📈 Maximum</div>
                    <div class="info-value" id="maxValue">--</div>
                </div>
            </div>
            
            <div class="reference-table">
                <h3>📋 Valeurs de référence</h3>
                <div class="ref-row">
                    <span><span class="ref-indicator" style="background: #ef4444;"></span>Hypoglycémie</span>
                    <span>&lt; 70 mg/dL</span>
                </div>
                <div class="ref-row">
                    <span><span class="ref-indicator" style="background: #10b981;"></span>Normal</span>
                    <span>70 - 140 mg/dL</span>
                </div>
                <div class="ref-row">
                    <span><span class="ref-indicator" style="background: #f59e0b;"></span>Élevé</span>
                    <span>140 - 200 mg/dL</span>
                </div>
                <div class="ref-row">
                    <span><span class="ref-indicator" style="background: #dc2626;"></span>Hyperglycémie</span>
                    <span>&gt; 200 mg/dL</span>
                </div>
            </div>
        </div>
    </div>

    <script>
        let glucoseData = [];
        let timeLabels = [];
        let measureCount = 0;
        let minGlucose = Infinity;
        let maxGlucose = -Infinity;
        const maxDataPoints = 20;
        
        // Créer le graphique
        const canvas = document.getElementById('glucoseChart');
        const ctx = canvas.getContext('2d');
        
        function drawChart() {{
            const width = canvas.width;
            const height = canvas.height;
            
            ctx.clearRect(0, 0, width, height);
            
            if (glucoseData.length === 0) {{
                ctx.fillStyle = '#999';
                ctx.font = '14px Arial';
                ctx.textAlign = 'center';
                ctx.fillText('En attente de données...', width/2, height/2);
                return;
            }}
            
            // Marges
            const margin = {{top: 20, right: 20, bottom: 30, left: 50}};
            const chartWidth = width - margin.left - margin.right;
            const chartHeight = height - margin.top - margin.bottom;
            
            // Échelles
            const maxY = 400;
            const minY = 0;
            const scaleY = chartHeight / (maxY - minY);
            const scaleX = chartWidth / (maxDataPoints - 1);
            
            // Zones de référence
            ctx.fillStyle = 'rgba(239, 68, 68, 0.1)';
            ctx.fillRect(margin.left, margin.top, chartWidth, (maxY - 200) * scaleY);
            
            ctx.fillStyle = 'rgba(16, 185, 129, 0.1)';
            ctx.fillRect(margin.left, margin.top + (maxY - 140) * scaleY, chartWidth, 70 * scaleY);
            
            // Grille
            ctx.strokeStyle = '#e0e0e0';
            ctx.lineWidth = 1;
            for (let i = 0; i <= 4; i++) {{
                const y = margin.top + (chartHeight / 4) * i;
                ctx.beginPath();
                ctx.moveTo(margin.left, y);
                ctx.lineTo(width - margin.right, y);
                ctx.stroke();
                
                // Labels Y
                const value = maxY - (maxY / 4) * i;
                ctx.fillStyle = '#666';
                ctx.font = '11px Arial';
                ctx.textAlign = 'right';
                ctx.fillText(value.toFixed(0), margin.left - 5, y + 4);
            }}
            
            // Tracer la courbe
            if (glucoseData.length > 1) {{
                ctx.strokeStyle = '#667eea';
                ctx.lineWidth = 3;
                ctx.beginPath();
                
                glucoseData.forEach((value, index) => {{
                    const x = margin.left + index * scaleX;
                    const y = margin.top + (maxY - value) * scaleY;
                    
                    if (index === 0) {{
                        ctx.moveTo(x, y);
                    }} else {{
                        ctx.lineTo(x, y);
                    }}
                }});
                
                ctx.stroke();
                
                // Points
                glucoseData.forEach((value, index) => {{
                    const x = margin.left + index * scaleX;
                    const y = margin.top + (maxY - value) * scaleY;
                    
                    ctx.fillStyle = value < 70 ? '#ef4444' : 
                                   value > 200 ? '#dc2626' : 
                                   value > 140 ? '#f59e0b' : '#10b981';
                    ctx.beginPath();
                    ctx.arc(x, y, 4, 0, Math.PI * 2);
                    ctx.fill();
                }});
            }}
            
            // Labels X
            ctx.fillStyle = '#666';
            ctx.font = '11px Arial';
            ctx.textAlign = 'center';
            ctx.fillText('Temps', width/2, height - 5);
        }}
        
        function updateChart(glucose) {{
            glucoseData.push(glucose);
            timeLabels.push(measureCount);
            
            if (glucoseData.length > maxDataPoints) {{
                glucoseData.shift();
                timeLabels.shift();
            }}
            
            measureCount++;
            minGlucose = Math.min(minGlucose, glucose);
            maxGlucose = Math.max(maxGlucose, glucose);
            
            document.getElementById('measureCount').textContent = measureCount;
            document.getElementById('minValue').textContent = minGlucose + ' mg/dL';
            document.getElementById('maxValue').textContent = maxGlucose + ' mg/dL';
            
            drawChart();
        }}
        
        function resizeCanvas() {{
            const container = canvas.parentElement;
            canvas.width = container.clientWidth - 40;
            canvas.height = container.clientHeight - 40;
            drawChart();
        }}
        
        window.addEventListener('resize', resizeCanvas);
        resizeCanvas();
        
        // Mise à jour automatique
        let lastUpdateTime = Date.now();
        
        function fetchGlucose() {{
            fetch('/api/glucose')
                .then(response => response.json())
                .then(data => {{
                    updateChart(data.glucose);
                    lastUpdateTime = Date.now();
                }})
                .catch(err => console.error('Erreur:', err));
        }}
        
        // Timer pour afficher le temps écoulé
        setInterval(() => {{
            const elapsed = Math.floor((Date.now() - lastUpdateTime) / 1000);
            document.getElementById('lastUpdate').textContent = elapsed + 's';
        }}, 1000);
        
        // Actualisation toutes les 2 secondes
        setInterval(fetchGlucose, 2000);
        fetchGlucose();
    </script>
</body>
</html>
"""
    return html

def api_glucose():
    """Retourne les données JSON pour l'API"""
    glucose = read_glucose()
    status, color, icon = get_glucose_status(glucose)
    
    # Construire manuellement le JSON pour éviter l'erreur de hash
    json_response = '{{"glucose": {}, "status": "{}", "color": "{}", "icon": "{}", "timestamp": {}}}'.format(
        glucose, status, color, icon, time.ticks_ms()
    )
    
    return json_response

def start_server(wlan):
    """Démarre le serveur web"""
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(1)
    
    ip = wlan.ifconfig()[0]
    print(f"\n{'='*50}")
    print(f"🩸 GLUCOMÈTRE ESP32 - SERVEUR ACTIF")
    print(f"{'='*50}")
    print(f"📱 Ouvrez sur votre iPhone:")
    print(f"   👉 http://{ip}")
    print(f"{'='*50}")
    print(f"🎛️  Tournez le potentiomètre pour simuler")
    print(f"    la glycémie en temps réel!\n")
    print("✅ En attente de connexions...\n")
    
    while True:
        try:
            cl, addr = s.accept()
            request = cl.recv(1024).decode('utf-8')
            
            # API pour obtenir la glycémie
            if '/api/glucose' in request:
                response = api_glucose()
                cl.send('HTTP/1.1 200 OK\r\n')
                cl.send('Content-Type: application/json\r\n')
                cl.send('Connection: close\r\n\r\n')
                cl.sendall(response)
                
                glucose = read_glucose()
                status, _, _ = get_glucose_status(glucose)
                print(f"📊 Mesure: {glucose} mg/dL - {status}")
            
            # Page principale
            else:
                response = web_page()
                cl.send('HTTP/1.1 200 OK\r\n')
                cl.send('Content-Type: text/html; charset=utf-8\r\n')
                cl.send('Connection: close\r\n\r\n')
                cl.sendall(response)
                print(f"👤 Connexion de {addr[0]}")
            
            cl.close()
            
        except OSError as e:
            cl.close()
        except KeyboardInterrupt:
            print("\n\n👋 Arrêt du serveur")
            s.close()
            led.off()
            break

def main():
    print("\n" + "="*50)
    print("   🩸 GLUCOMÈTRE ESP32 - MicroPython")
    print("="*50 + "\n")
    
    wlan = connect_wifi()
    
    if not wlan:
        print("\n⚠️ ÉCHEC - Pas de WiFi")
        return
    
    try:
        start_server(wlan)
    except Exception as e:
        print(f"\n❌ Erreur: {e}")
        led.off()

if __name__ == "__main__":
    main()