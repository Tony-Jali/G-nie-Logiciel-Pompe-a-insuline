import network
import socket
import time
import json
from machine import Pin, ADC, Timer

# Configuration WiFi
SSID = "iPhone tony"
PASSWORD = "Tony 237"

# Configuration matérielle
led = Pin(2, Pin.OUT)
potentiometre = ADC(Pin(34))  # GPIO 34 pour le potentiomètre
potentiometre.atten(ADC.ATTN_11DB)  # Plage 0-3.3V
potentiometre.width(ADC.WIDTH_12BIT)  # Résolution 12 bits (0-4095)

# Relais pour contrôle de la pompe à insuline
relay_pump = Pin(10, Pin.OUT)
relay_pump.value(0)  # Pompe éteinte au démarrage

# Fichier de stockage des utilisateurs
USERS_FILE = "users.json"

# Variables globales
current_glucose = 0
readings_history = []
last_stable_value = 0
readings_buffer = []
STABILITY_THRESHOLD = 5  # Seuil de variation acceptable en mg/dL

# Variables pour l'injection d'insuline
injection_in_progress = False
injection_start_time = 0
target_dose = 0.0
injected_dose = 0.0
injection_timer = None
INJECTION_RATE = 0.1  # Unités par seconde

# Session active
active_sessions = {}  # {session_id: username}

# Paramètres pour le calcul d'insuline
TARGET_GLUCOSE = 100
INSULIN_SENSITIVITY = 50
CARB_RATIO = 15

def load_users():
    """Charge les utilisateurs depuis le fichier JSON"""
    try:
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    except:
        # Si le fichier n'existe pas, créer une structure vide
        return {"users": []}

def save_users(users_data):
    """Sauvegarde les utilisateurs dans le fichier JSON"""
    try:
        with open(USERS_FILE, 'w') as f:
            json.dump(users_data, f)
        return True
    except:
        return False

def find_user(username):
    """Recherche un utilisateur par son nom"""
    users_data = load_users()
    for user in users_data["users"]:
        if user["username"] == username:
            return user
    return None

def register_user(username, password, email, age, weight):
    """Enregistre un nouvel utilisateur"""
    users_data = load_users()
    
    print(f"📝 Tentative d'inscription: {username}, {email}, age={age}, weight={weight}")
    
    # Vérifier si l'utilisateur existe déjà
    if find_user(username):
        print(f"❌ Utilisateur déjà existant: {username}")
        return False, "Nom d'utilisateur déjà utilisé"
    
    # Convertir age et weight en int si ce sont des strings
    try:
        age = int(age)
        weight = int(weight)
    except (ValueError, TypeError) as e:
        print(f"❌ Erreur de conversion: {e}")
        return False, "Age et poids doivent être des nombres"
    
    # Créer le nouvel utilisateur
    new_user = {
        "username": username,
        "password": password,  # En production, utiliser un hash!
        "email": email,
        "age": age,
        "weight": weight,
        "created_at": time.time(),
        "injection_history": []
    }
    
    users_data["users"].append(new_user)
    
    if save_users(users_data):
        print(f"✅ Utilisateur enregistré: {username}")
        return True, "Inscription réussie"
    else:
        print(f"❌ Erreur sauvegarde: {username}")
        return False, "Erreur lors de l'enregistrement"

def authenticate_user(username, password):
    """Authentifie un utilisateur"""
    user = find_user(username)
    if user and user["password"] == password:
        # Créer une session
        session_id = str(time.ticks_ms())
        active_sessions[session_id] = username
        print(f"✅ Connexion réussie: {username}")
        return True, session_id
    return False, None

def logout_user(session_id):
    """Déconnecte un utilisateur"""
    if session_id in active_sessions:
        username = active_sessions[session_id]
        del active_sessions[session_id]
        print(f"👋 Déconnexion: {username}")
        return True
    return False

def is_authenticated(session_id):
    """Vérifie si une session est valide"""
    return session_id in active_sessions

def get_current_user(session_id):
    """Récupère le nom d'utilisateur de la session"""
    return active_sessions.get(session_id, None)

def log_injection(username, glucose, dose, duration):
    """Enregistre une injection dans l'historique du patient"""
    users_data = load_users()
    for user in users_data["users"]:
        if user["username"] == username:
            injection_log = {
                "timestamp": time.time(),
                "glucose": glucose,
                "dose": dose,
                "duration": duration
            }
            user["injection_history"].append(injection_log)
            save_users(users_data)
            break

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
    """Lit le potentiomètre et convertit en taux de glycémie"""
    global current_glucose, last_stable_value
    
    samples = []
    for _ in range(10):
        adc_value = potentiometre.read()
        samples.append(adc_value)
        time.sleep_ms(5)
    
    avg_adc = sum(samples) // len(samples)
    glucose = int((avg_adc / 4095) * 380 + 20)
    glucose = round(glucose / 10) * 10
    
    if abs(glucose - last_stable_value) < STABILITY_THRESHOLD:
        glucose = last_stable_value
    else:
        last_stable_value = glucose
    
    current_glucose = glucose
    return glucose

def calculate_insulin_dose(glucose):
    """Calcule la dose d'insuline recommandée"""
    if glucose <= 140:
        return 0.0, "Aucune insuline nécessaire"
    
    dose = (glucose - TARGET_GLUCOSE) / INSULIN_SENSITIVITY
    dose = round(dose * 2) / 2
    
    if dose > 10:
        return 10.0, "⚠️ Dose élevée - Consulter un médecin"
    elif dose > 5:
        return dose, "Dose importante - Vérifier avant injection"
    elif dose > 0:
        return dose, "Dose de correction recommandée"
    else:
        return 0.0, "Aucune insuline nécessaire"

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

def start_injection(dose, username):
    """Démarre l'injection d'insuline"""
    global injection_in_progress, injection_start_time, target_dose, injected_dose
    
    if injection_in_progress:
        return False, "Injection déjà en cours"
    
    if dose <= 0:
        return False, "Dose invalide"
    
    injection_in_progress = True
    injection_start_time = time.time()
    target_dose = dose
    injected_dose = 0.0
    
    relay_pump.value(1)
    led.value(1)
    
    print(f"💉 INJECTION DÉMARRÉE - Patient: {username} - Dose: {dose} unités")
    return True, f"Injection de {dose} unités démarrée"

def stop_injection(username):
    """Arrête l'injection d'insuline"""
    global injection_in_progress, injected_dose, injection_start_time
    
    if not injection_in_progress:
        return False, "Aucune injection en cours"
    
    relay_pump.value(0)
    led.value(0)
    
    injection_in_progress = False
    final_dose = injected_dose
    duration = time.time() - injection_start_time
    
    # Enregistrer l'injection
    glucose = read_glucose()
    log_injection(username, glucose, final_dose, duration)
    
    print(f"🛑 INJECTION ARRÊTÉE - Patient: {username} - Dose: {final_dose:.2f} unités")
    return True, f"Injection arrêtée - {final_dose:.2f} unités injectées"

def update_injection():
    """Met à jour l'état de l'injection"""
    global injection_in_progress, injected_dose, target_dose
    
    if not injection_in_progress:
        return
    
    elapsed_time = time.time() - injection_start_time
    injected_dose = min(elapsed_time * INJECTION_RATE, target_dose)
    
    if injected_dose >= target_dose:
        # Trouver l'utilisateur de la session active
        for session_id, username in active_sessions.items():
            stop_injection(username)
            break

def get_injection_status():
    """Retourne le statut actuel de l'injection"""
    if injection_in_progress:
        progress = (injected_dose / target_dose * 100) if target_dose > 0 else 0
        return {
            'active': True,
            'target_dose': target_dose,
            'injected_dose': round(injected_dose, 2),
            'progress': round(progress, 1),
            'remaining': round(target_dose - injected_dose, 2)
        }
    else:
        return {
            'active': False,
            'target_dose': 0,
            'injected_dose': 0,
            'progress': 0,
            'remaining': 0
        }

def login_page():
    """Page de connexion"""
    html = """<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Connexion - Glucomètre ESP32</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #e0f2fe 0%, #bfdbfe 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        
        .container {
            max-width: 450px;
            width: 100%;
        }
        
        .card {
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            padding: 24px;
        }
        
        .logo {
            text-align: center;
            margin-bottom: 24px;
        }
        
        .logo-icon {
            font-size: 3em;
            margin-bottom: 10px;
        }
        
        h1 {
            color: #1e293b;
            text-align: center;
            margin-bottom: 8px;
            font-size: 24px;
            font-weight: 600;
        }
        
        .subtitle {
            text-align: center;
            color: #64748b;
            margin-bottom: 24px;
            font-size: 14px;
        }
        
        .tabs-list {
            display: flex;
            gap: 4px;
            border-bottom: 2px solid #e2e8f0;
            margin-bottom: 20px;
        }
        
        .tab-button {
            flex: 1;
            padding: 12px 16px;
            background: none;
            border: none;
            border-bottom: 2px solid transparent;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            color: #64748b;
            transition: all 0.2s;
            margin-bottom: -2px;
        }
        
        .tab-button:hover {
            color: #3b82f6;
        }
        
        .tab-button.active {
            color: #3b82f6;
            border-bottom-color: #3b82f6;
        }
        
        .tab-content {
            display: none;
        }
        
        .tab-content.active {
            display: block;
            animation: fadeIn 0.3s;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        
        .form-group {
            margin-bottom: 16px;
        }
        
        label {
            display: block;
            font-size: 14px;
            font-weight: 500;
            color: #1e293b;
            margin-bottom: 6px;
        }
        
        input {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            font-size: 14px;
            transition: border-color 0.2s;
        }
        
        input:focus {
            outline: none;
            border-color: #3b82f6;
        }
        
        .btn {
            width: 100%;
            padding: 12px 16px;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
            margin-top: 10px;
        }
        
        .btn-primary {
            background: #3b82f6;
            color: white;
        }
        
        .btn-primary:hover {
            background: #2563eb;
        }
        
        .alert {
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 20px;
            display: none;
            font-size: 14px;
        }
        
        .alert.success {
            background: #dcfce7;
            color: #166534;
            border: 1px solid #86efac;
        }
        
        .alert.error {
            background: #fee2e2;
            color: #991b1b;
            border: 1px solid #fca5a5;
        }
        
        .alert.show {
            display: block;
        }
        
        .row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }
        
        @media (max-width: 480px) {
            .card {
                padding: 20px;
            }
            .row {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="logo">
                <div class="logo-icon">🩸</div>
                <h1>Glucomètre ESP32</h1>
                <p class="subtitle">Système de gestion de pompe à insuline</p>
            </div>
            
            <div class="tabs-list">
                <button class="tab-button active" onclick="showTab('login')">Connexion</button>
                <button class="tab-button" onclick="showTab('register')">Inscription</button>
            </div>
            
            <div id="alertBox" class="alert"></div>
            
            <!-- Formulaire de connexion -->
            <div id="loginTab" class="tab-content active">
                <form onsubmit="handleLogin(event)">
                    <div class="form-group">
                        <label for="loginUsername">Nom d'utilisateur</label>
                        <input type="text" id="loginUsername" required>
                    </div>
                    <div class="form-group">
                        <label for="loginPassword">Mot de passe</label>
                        <input type="password" id="loginPassword" required>
                    </div>
                    <button type="submit" class="btn btn-primary">Se connecter</button>
                </form>
            </div>
            
            <!-- Formulaire d'inscription -->
            <div id="registerTab" class="tab-content">
                <form onsubmit="handleRegister(event)">
                    <div class="form-group">
                        <label for="regUsername">Nom d'utilisateur</label>
                        <input type="text" id="regUsername" required minlength="3">
                    </div>
                    <div class="form-group">
                        <label for="regEmail">Email</label>
                        <input type="email" id="regEmail" required>
                    </div>
                    <div class="form-group">
                        <label for="regPassword">Mot de passe</label>
                        <input type="password" id="regPassword" required minlength="6">
                    </div>
                    <div class="row">
                        <div class="form-group">
                            <label for="regAge">Âge</label>
                            <input type="number" id="regAge" required min="1" max="120">
                        </div>
                        <div class="form-group">
                            <label for="regWeight">Poids (kg)</label>
                            <input type="number" id="regWeight" required min="20" max="300">
                        </div>
                    </div>
                    <button type="submit" class="btn btn-primary">S'inscrire</button>
                </form>
            </div>
        </div>
    </div>

    <script>
        // Fonction pour changer d'onglet
        function showTab(tabName) {
            // Cacher tous les contenus
            var contents = document.getElementsByClassName('tab-content');
            for (var i = 0; i < contents.length; i++) {
                contents[i].classList.remove('active');
            }
            
            // Désactiver tous les boutons
            var buttons = document.getElementsByClassName('tab-button');
            for (var i = 0; i < buttons.length; i++) {
                buttons[i].classList.remove('active');
            }
            
            // Afficher l'onglet sélectionné
            if (tabName === 'login') {
                document.getElementById('loginTab').classList.add('active');
                buttons[0].classList.add('active');
            } else if (tabName === 'register') {
                document.getElementById('registerTab').classList.add('active');
                buttons[1].classList.add('active');
            }
            
            hideAlert();
        }
        
        function showAlert(message, type) {
            var alertBox = document.getElementById('alertBox');
            alertBox.textContent = message;
            alertBox.className = 'alert ' + type + ' show';
        }
        
        function hideAlert() {
            var alertBox = document.getElementById('alertBox');
            alertBox.className = 'alert';
        }
        
        function handleLogin(event) {
            event.preventDefault();
            
            var username = document.getElementById('loginUsername').value;
            var password = document.getElementById('loginPassword').value;
            
            // Créer la requête manuellement pour compatibilité
            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/login', true);
            xhr.setRequestHeader('Content-Type', 'application/json');
            
            xhr.onload = function() {
                if (xhr.status === 200) {
                    var data = JSON.parse(xhr.responseText);
                    if (data.status === 'success') {
                        showAlert('Connexion réussie! Redirection...', 'success');
                        setTimeout(function() {
                            window.location.href = '/dashboard?session=' + data.session_id;
                        }, 1000);
                    } else {
                        showAlert(data.message, 'error');
                    }
                } else {
                    showAlert('Erreur de connexion', 'error');
                }
            };
            
            xhr.onerror = function() {
                showAlert('Erreur de connexion', 'error');
            };
            
            var payload = JSON.stringify({
                username: username,
                password: password
            });
            
            xhr.send(payload);
        }
        
        function handleRegister(event) {
            event.preventDefault();
            
            var username = document.getElementById('regUsername').value;
            var email = document.getElementById('regEmail').value;
            var password = document.getElementById('regPassword').value;
            var age = document.getElementById('regAge').value;
            var weight = document.getElementById('regWeight').value;
            
            // Créer la requête manuellement
            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/register', true);
            xhr.setRequestHeader('Content-Type', 'application/json');
            
            xhr.onload = function() {
                if (xhr.status === 200) {
                    var data = JSON.parse(xhr.responseText);
                    if (data.status === 'success') {
                        showAlert('Inscription réussie! Vous pouvez vous connecter.', 'success');
                        setTimeout(function() {
                            showTab('login');
                            document.getElementById('loginUsername').value = username;
                        }, 1500);
                    } else {
                        showAlert(data.message, 'error');
                    }
                } else {
                    showAlert('Erreur lors de inscription', 'error');
                }
            };
            
            xhr.onerror = function() {
                showAlert('Erreur lors de inscription', 'error');
            };
            
            var payload = JSON.stringify({
                username: username,
                email: email,
                password: password,
                age: parseInt(age),
                weight: parseInt(weight)
            });
            
            xhr.send(payload);
        }
    </script>
</body>
</html>
"""
    return html

def dashboard_page(session_id):
    """Page du tableau de bord (application principale)"""
    username = get_current_user(session_id)
    user = find_user(username)
    
    glucose = read_glucose()
    status, color, icon = get_glucose_status(glucose)
    insulin_dose, insulin_recommendation = calculate_insulin_dose(glucose)
    injection_status = get_injection_status()
    
    # Informations patient
    age = user.get('age', 'N/A')
    weight = user.get('weight', 'N/A')
    email = user.get('email', 'N/A')
    
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard - Glucomètre ESP32</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #e0f2fe 0%, #bfdbfe 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        
        .card {{
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            padding: 24px;
            margin-bottom: 20px;
        }}
        
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }}
        
        .header h1 {{
            font-size: 32px;
            color: #1e293b;
            font-weight: 600;
        }}
        
        .header p {{
            color: #64748b;
            font-size: 14px;
        }}
        
        .user-info {{
            display: flex;
            align-items: center;
            gap: 15px;
        }}
        
        .user-avatar {{
            width: 50px;
            height: 50px;
            background: #3b82f6;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5em;
            color: white;
        }}
        
        .user-details h2 {{
            color: #1e293b;
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 3px;
        }}
        
        .user-details p {{
            color: #64748b;
            font-size: 14px;
        }}
        
        .btn {{
            padding: 10px 20px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 500;
            font-size: 14px;
            transition: all 0.2s;
        }}
        
        .btn-logout {{
            background: #ef4444;
            color: white;
        }}
        
        .btn-logout:hover {{
            background: #dc2626;
        }}
        
        .btn-primary {{
            background: #3b82f6;
            color: white;
            width: 100%;
        }}
        
        .btn-primary:hover {{
            background: #2563eb;
        }}
        
        .btn-primary:disabled {{
            background: #94a3b8;
            cursor: not-allowed;
        }}
        
        .btn-danger {{
            background: #ef4444;
            color: white;
            width: 100%;
        }}
        
        .btn-danger:hover {{
            background: #dc2626;
        }}
        
        .btn-danger:disabled {{
            background: #94a3b8;
            cursor: not-allowed;
        }}
        
        .grid {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 20px;
        }}
        
        @media (min-width: 768px) {{
            .grid {{
                grid-template-columns: 1fr 1fr;
            }}
        }}
        
        .card-title {{
            font-size: 18px;
            font-weight: 600;
            color: #1e293b;
            margin-bottom: 16px;
        }}
        
        .glycemia-display {{
            text-align: center;
            padding: 20px;
        }}
        
        .glycemia-value {{
            font-size: 72px;
            font-weight: 700;
            margin-bottom: 8px;
            color: #1e293b;
        }}
        
        .color-normal {{
            color: #10b981;
        }}
        
        .color-low {{
            color: #f59e0b;
        }}
        
        .color-high {{
            color: #f59e0b;
        }}
        
        .color-critical {{
            color: #ef4444;
        }}
        
        .glycemia-unit {{
            color: #64748b;
            font-size: 18px;
            margin-bottom: 16px;
        }}
        
        .glycemia-status {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            margin-top: 12px;
        }}
        
        .badge {{
            display: inline-block;
            padding: 6px 16px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 500;
        }}
        
        .badge-normal {{
            background: #dcfce7;
            color: #166534;
        }}
        
        .badge-warning {{
            background: #fef3c7;
            color: #92400e;
        }}
        
        .badge-danger {{
            background: #fee2e2;
            color: #991b1b;
        }}
        
        .separator {{
            height: 1px;
            background: #e2e8f0;
            margin: 16px 0;
        }}
        
        .info-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
        }}
        
        .info-label {{
            color: #64748b;
            font-size: 14px;
        }}
        
        .info-value {{
            color: #1e293b;
            font-size: 18px;
            font-weight: 600;
        }}
        
        .insulin-value {{
            font-size: 48px;
            font-weight: 700;
            color: #3b82f6;
            text-align: center;
            margin: 20px 0;
        }}
        
        .control-buttons {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-top: 16px;
        }}
        
        .progress-container {{
            margin-top: 16px;
        }}
        
        .progress-bar {{
            width: 100%;
            height: 8px;
            background: #e2e8f0;
            border-radius: 999px;
            overflow: hidden;
            margin-bottom: 12px;
        }}
        
        .progress-fill {{
            height: 100%;
            background: #3b82f6;
            transition: width 0.3s ease;
            border-radius: 999px;
        }}
        
        .progress-info {{
            display: flex;
            justify-content: space-between;
            font-size: 14px;
            color: #64748b;
            margin-bottom: 8px;
        }}
        
        .pump-indicator {{
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin-right: 8px;
        }}
        
        .pump-on {{
            background: #10b981;
            animation: pulse-pump 1s infinite;
        }}
        
        .pump-off {{
            background: #94a3b8;
        }}
        
        @keyframes pulse-pump {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
        }}
        
        .alert {{
            padding: 12px 16px;
            border-radius: 6px;
            margin-bottom: 16px;
            font-size: 14px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        
        .alert-warning {{
            background: #fef3c7;
            color: #92400e;
            border: 1px solid #fde68a;
        }}
        
        .alert-danger {{
            background: #fee2e2;
            color: #991b1b;
            border: 1px solid #fca5a5;
        }}
        
        .alert-success {{
            background: #dcfce7;
            color: #166534;
            border: 1px solid #86efac;
        }}
        
        .hidden {{
            display: none;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="header">
                <div class="user-info">
                    <div class="user-avatar">👤</div>
                    <div class="user-details">
                        <h2>{username}</h2>
                        <p>{age} ans • {weight} kg • {email}</p>
                    </div>
                </div>
                <button class="btn-logout" onclick="logout()">Déconnexion</button>
            </div>
        </div>
        
        <div class="grid">
            <!-- Carte Glycémie -->
            <div class="card">
                <h3 class="card-title">📊 Glycémie actuelle</h3>
                <div class="glycemia-display">
                    <div class="glycemia-value" id="glycemiaValue">{glucose}</div>
                    <div class="glycemia-unit">mg/dL</div>
                    <div class="glycemia-status">
                        <span id="glycemiaIcon">{icon}</span>
                        <span class="badge badge-normal" id="glycemiaBadge">{status}</span>
                    </div>
                </div>
            </div>
            
            <!-- Carte Dose d'insuline -->
            <div class="card">
                <h3 class="card-title">💉 Dose recommandée</h3>
                <div class="insulin-value" id="insulinDose">{insulin_dose}</div>
                <div style="text-align: center; color: #64748b; font-size: 14px; margin-bottom: 16px;">unités</div>
                <div style="text-align: center; padding: 8px; background: #f1f5f9; border-radius: 6px; font-size: 13px; color: #64748b;" id="insulinRec">{insulin_recommendation}</div>
            </div>
        </div>
        
        <!-- Carte Contrôle de la pompe -->
        <div class="card">
            <h3 class="card-title">🎛️ Contrôle de la pompe</h3>
            
            <div id="alertBox"></div>
            
            <div class="info-row">
                <span class="info-label">État de la pompe</span>
                <span class="info-value" id="pumpStatus">
                    <span class="pump-indicator pump-off"></span>Arrêtée
                </span>
            </div>
            
            <div class="separator"></div>
            
            <div class="info-row">
                <span class="info-label">Dose cible</span>
                <span class="info-value" id="targetDose">0.0 U</span>
            </div>
            
            <div class="info-row">
                <span class="info-label">Dose injectée</span>
                <span class="info-value" id="injectedDose">0.0 U</span>
            </div>
            
            <div class="info-row">
                <span class="info-label">Restant</span>
                <span class="info-value" id="remainingDose">0.0 U</span>
            </div>
            
            <div class="progress-container">
                <div class="progress-info">
                    <span>Progression</span>
                    <span id="progressText">0%</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" id="progressBar" style="width: 0%;"></div>
                </div>
            </div>
            
            <div class="control-buttons">
                <button class="btn btn-primary" id="btnStart" onclick="startInjection()">
                    ▶️ Injecter
                </button>
                <button class="btn btn-danger" id="btnStop" onclick="stopInjection()" disabled>
                    ⏹️ Arrêter
                </button>
            </div>
        </div>
        
        <!-- Avertissement -->
        <div class="alert alert-warning">
            ⚠️ <strong>AVERTISSEMENT:</strong> Ceci est une simulation éducative. Ne JAMAIS utiliser ce système pour une injection réelle sans supervision médicale professionnelle.
        </div>
    </div>

    <script>
        const sessionId = new URLSearchParams(window.location.search).get('session');
        
        function logout() {{
            if (confirm('Voulez-vous vraiment vous déconnecter?')) {{
                fetch('/api/logout?session=' + sessionId, {{method: 'POST'}})
                    .then(() => window.location.href = '/')
                    .catch(err => console.error('Erreur:', err));
            }}
        }}
        
        function updateDisplay(data) {{
            // Mise à jour de la glycémie
            document.getElementById('glycemiaValue').textContent = data.glucose;
            document.getElementById('insulinDose').textContent = data.insulin_dose;
            document.getElementById('insulinRec').textContent = data.insulin_recommendation;
            
            // Déterminer le statut et la couleur
            let statusClass = 'color-normal';
            let badgeClass = 'badge-normal';
            let icon = '➖';
            let statusText = data.status;
            
            if (data.glucose < 70) {{
                statusClass = 'color-low';
                badgeClass = 'badge-warning';
                icon = '⬇️';
            }} else if (data.glucose > 200) {{
                statusClass = 'color-critical';
                badgeClass = 'badge-danger';
                icon = '⬆️';
            }} else if (data.glucose > 140) {{
                statusClass = 'color-high';
                badgeClass = 'badge-warning';
                icon = '⬆️';
            }}
            
            document.getElementById('glycemiaValue').className = 'glycemia-value ' + statusClass;
            document.getElementById('glycemiaIcon').textContent = icon;
            document.getElementById('glycemiaBadge').className = 'badge ' + badgeClass;
            document.getElementById('glycemiaBadge').textContent = statusText;
            
            // Mise à jour du statut d'injection
            const injStatus = data.injection_status;
            document.getElementById('targetDose').textContent = injStatus.target_dose.toFixed(1) + ' U';
            document.getElementById('injectedDose').textContent = injStatus.injected_dose.toFixed(2) + ' U';
            document.getElementById('remainingDose').textContent = injStatus.remaining.toFixed(2) + ' U';
            
            const progress = injStatus.progress || 0;
            document.getElementById('progressBar').style.width = progress + '%';
            document.getElementById('progressText').textContent = progress.toFixed(0) + '%';
            
            // État de la pompe
            const btnStart = document.getElementById('btnStart');
            const btnStop = document.getElementById('btnStop');
            const pumpStatus = document.getElementById('pumpStatus');
            
            if (injStatus.active) {{
                btnStart.disabled = true;
                btnStop.disabled = false;
                pumpStatus.innerHTML = '<span class="pump-indicator pump-on"></span>En fonctionnement';
            }} else {{
                btnStart.disabled = false;
                btnStop.disabled = true;
                pumpStatus.innerHTML = '<span class="pump-indicator pump-off"></span>Arrêtée';
            }}
        }}
        
        function startInjection() {{
            const dose = parseFloat(document.getElementById('insulinDose').textContent);
            if (dose <= 0) {{
                alert('Aucune insuline nécessaire!');
                return;
            }}
            
            if (confirm(`Voulez-vous injecter ${{dose}} unités d'insuline?`)) {{
                fetch('/api/injection/start?session=' + sessionId, {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{dose: dose}})
                }})
                .then(response => response.json())
                .then(data => console.log('Injection démarrée:', data))
                .catch(err => console.error('Erreur:', err));
            }}
        }}
        
        function stopInjection() {{
            if (confirm('Voulez-vous arrêter l\'injection en cours?')) {{
                fetch('/api/injection/stop?session=' + sessionId, {{
                    method: 'POST'
                }})
                .then(response => response.json())
                .then(data => {{
                    console.log('Injection arrêtée:', data);
                    alert(data.message);
                }})
                .catch(err => console.error('Erreur:', err));
            }}
        }}
        
        function fetchData() {{
            fetch('/api/glucose?session=' + sessionId)
                .then(response => response.json())
                .then(data => updateDisplay(data))
                .catch(err => console.error('Erreur:', err));
        }}
        
        setInterval(fetchData, 500);
        fetchData();
    </script>
</body>
</html>
"""
    return html

def parse_json_body(body):
    """Parse le corps JSON de la requête"""
    try:
        return json.loads(body)
    except:
        return None

def api_glucose(session_id):
    """API glucose avec vérification de session"""
    if not is_authenticated(session_id):
        return '{{"status": "error", "message": "Non authentifié"}}'
    
    glucose = read_glucose()
    status, color, icon = get_glucose_status(glucose)
    insulin_dose, insulin_recommendation = calculate_insulin_dose(glucose)
    injection_status = get_injection_status()
    
    return '{{"glucose": {}, "status": "{}", "color": "{}", "icon": "{}", "insulin_dose": {}, "insulin_recommendation": "{}", "injection_status": {{"active": {}, "target_dose": {}, "injected_dose": {}, "progress": {}, "remaining": {}}}}}'.format(
        glucose, status, color, icon, insulin_dose, insulin_recommendation,
        'true' if injection_status['active'] else 'false',
        injection_status['target_dose'],
        injection_status['injected_dose'],
        injection_status['progress'],
        injection_status['remaining']
    )

def start_server(wlan):
    """Démarre le serveur web avec authentification"""
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(1)
    
    ip = wlan.ifconfig()[0]
    print(f"\n{'='*50}")
    print(f"🩸 GLUCOMÈTRE ESP32 - SERVEUR ACTIF")
    print(f"💉 Système de Pompe à Insuline Sécurisé")
    print(f"{'='*50}")
    print(f"📱 URL d'accès:")
    print(f"   👉 http://{ip}")
    print(f"{'='*50}\n")
    print("✅ En attente de connexions...\n")
    
    while True:
        try:
            update_injection()
            
            cl, addr = s.accept()
            request = cl.recv(2048).decode('utf-8')
            
            # Extraire la session ID si présente
            session_id = None
            if 'session=' in request:
                session_start = request.find('session=') + 8
                session_end = request.find(' ', session_start)
                if session_end == -1:
                    session_end = request.find('&', session_start)
                if session_end == -1:
                    session_end = len(request)
                session_id = request[session_start:session_end]
            
            # API Login
            if 'POST /api/login' in request:
                body_start = request.find('\r\n\r\n') + 4
                body = request[body_start:]
                data = parse_json_body(body)
                
                if data:
                    success, session = authenticate_user(data['username'], data['password'])
                    if success:
                        response = '{{"status": "success", "session_id": "{}"}}'.format(session)
                    else:
                        response = '{{"status": "error", "message": "Identifiants incorrects"}}'
                else:
                    response = '{{"status": "error", "message": "Données invalides"}}'
                
                cl.send('HTTP/1.1 200 OK\r\n')
                cl.send('Content-Type: application/json\r\n')
                cl.send('Connection: close\r\n\r\n')
                cl.sendall(response)
            
            # API Register
            elif 'POST /api/register' in request:
                print("📥 Requête d'inscription reçue")
                body_start = request.find('\r\n\r\n') + 4
                body = request[body_start:]
                print(f"📄 Body brut: {body[:100]}")  # Afficher les 100 premiers caractères
                
                data = parse_json_body(body)
                print(f"📊 Data parsé: {data}")
                
                if data:
                    try:
                        success, message = register_user(
                            data['username'],
                            data['password'],
                            data['email'],
                            data['age'],
                            data['weight']
                        )
                        if success:
                            response = '{{"status": "success", "message": "{}"}}'.format(message)
                            print(f"✅ Inscription réussie")
                        else:
                            response = '{{"status": "error", "message": "{}"}}'.format(message)
                            print(f"❌ Inscription échouée: {message}")
                    except Exception as e:
                        print(f"❌ Exception: {e}")
                        response = '{{"status": "error", "message": "Erreur serveur: {}"}}'.format(str(e))
                else:
                    print("❌ Données JSON invalides")
                    response = '{{"status": "error", "message": "Données invalides"}}'
                
                cl.send('HTTP/1.1 200 OK\r\n')
                cl.send('Content-Type: application/json\r\n')
                cl.send('Connection: close\r\n\r\n')
                cl.sendall(response)
            
            # API Logout
            elif 'POST /api/logout' in request and session_id:
                logout_user(session_id)
                response = '{{"status": "success"}}'
                cl.send('HTTP/1.1 200 OK\r\n')
                cl.send('Content-Type: application/json\r\n')
                cl.send('Connection: close\r\n\r\n')
                cl.sendall(response)
            
            # API Injection Start
            elif 'POST /api/injection/start' in request and session_id:
                if is_authenticated(session_id):
                    body_start = request.find('\r\n\r\n') + 4
                    body = request[body_start:]
                    data = parse_json_body(body)
                    
                    if data:
                        username = get_current_user(session_id)
                        success, message = start_injection(data['dose'], username)
                        status = "success" if success else "error"
                        response = '{{"status": "{}", "message": "{}"}}'.format(status, message)
                    else:
                        response = '{{"status": "error", "message": "Données invalides"}}'
                else:
                    response = '{{"status": "error", "message": "Non authentifié"}}'
                
                cl.send('HTTP/1.1 200 OK\r\n')
                cl.send('Content-Type: application/json\r\n')
                cl.send('Connection: close\r\n\r\n')
                cl.sendall(response)
            
            # API Injection Stop
            elif 'POST /api/injection/stop' in request and session_id:
                if is_authenticated(session_id):
                    username = get_current_user(session_id)
                    success, message = stop_injection(username)
                    status = "success" if success else "error"
                    response = '{{"status": "{}", "message": "{}"}}'.format(status, message)
                else:
                    response = '{{"status": "error", "message": "Non authentifié"}}'
                
                cl.send('HTTP/1.1 200 OK\r\n')
                cl.send('Content-Type: application/json\r\n')
                cl.send('Connection: close\r\n\r\n')
                cl.sendall(response)
            
            # API Glucose
            elif '/api/glucose' in request and session_id:
                response = api_glucose(session_id)
                cl.send('HTTP/1.1 200 OK\r\n')
                cl.send('Content-Type: application/json\r\n')
                cl.send('Connection: close\r\n\r\n')
                cl.sendall(response)
            
            # Dashboard (nécessite authentification)
            elif '/dashboard' in request and session_id:
                if is_authenticated(session_id):
                    response = dashboard_page(session_id)
                    cl.send('HTTP/1.1 200 OK\r\n')
                    cl.send('Content-Type: text/html; charset=utf-8\r\n')
                    cl.send('Connection: close\r\n\r\n')
                    cl.sendall(response)
                else:
                    # Redirection vers login
                    cl.send('HTTP/1.1 302 Found\r\n')
                    cl.send('Location: /\r\n')
                    cl.send('Connection: close\r\n\r\n')
            
            # Page de connexion (par défaut)
            else:
                response = login_page()
                cl.send('HTTP/1.1 200 OK\r\n')
                cl.send('Content-Type: text/html; charset=utf-8\r\n')
                cl.send('Connection: close\r\n\r\n')
                cl.sendall(response)
            
            cl.close()
            
        except OSError as e:
            cl.close()
        except KeyboardInterrupt:
            print("\n\n👋 Arrêt du serveur")
            stop_injection("system")
            s.close()
            led.off()
            break

def main():
    print("\n" + "="*50)
    print("   🩸 GLUCOMÈTRE ESP32 - MicroPython")
    print("   💉 Système Sécurisé avec Authentification")
    print("="*50 + "\n")
    
    wlan = connect_wifi()
    
    if not wlan:
        print("\n⚠️ ÉCHEC - Pas de WiFi")
        return
    
    try:
        start_server(wlan)
    except Exception as e:
        print(f"\n❌ Erreur: {e}")
        stop_injection("system")
        led.off()

if __name__ == "__main__":
    main()

