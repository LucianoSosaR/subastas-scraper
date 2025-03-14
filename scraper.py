import os
import time
import re
import sqlite3
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# =========================================
# CONFIGURACIÓN
# =========================================
SCRAPE_URL = "https://www.bavastronline.com.uy/auctions/2161"  # Cambia el link a la subasta que desees

options = Options()
options.add_argument("--headless")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--disable-blink-features=AutomationControlled")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

def parse_auction_id(url: str) -> str:
    match = re.search(r"auctions/(\d+)", url)
    return match.group(1) if match else "N/A"

# =========================================
# FUNCIONES DE SCRAPING
# =========================================
def scroll_down():
    """Realiza scroll hasta que se carguen todos los artículos."""
    scroll_pause_time = 2
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(scroll_pause_time)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

def scrape_subastas(auction_url: str):
    """Carga la página, hace scroll completo y extrae la información de cada artículo.
       Retorna una lista de tuplas: (lote, descripcion, precio, ofertas, imagen, enlace, subasta_id).
    """
    driver.get(auction_url)
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.XPATH, "//*[@id='root']/div[1]/div/div/div[4]/div/div/div"))
    )
    
    subasta_id = parse_auction_id(auction_url)
    scroll_down()
    
    articulos = driver.execute_script("""
    let elements = document.querySelectorAll('.MuiCard-root');
    let data = [];
    elements.forEach((item) => {
        let loteElem = item.querySelector('.MuiTypography-body2');
        let lote = loteElem ? loteElem.innerText.trim() : 'N/A';
        
        let desElems = item.querySelectorAll('.MuiTypography-body2');
        let descripcion = desElems.length > 1 ? desElems[1].innerText.trim() : 'N/A';
        
        let precioElem = item.querySelector('.MuiTypography-body1');
        let precio = precioElem ? precioElem.innerText.trim() : 'N/A';
        
        let ofertas = 0;
        let pElems = item.querySelectorAll('p');
        pElems.forEach((p) => {
            if (p.innerText.includes("Ofertas:")) {
                let bElem = p.querySelector("b");
                if(bElem) {
                    let num = parseInt(bElem.innerText.replace(/[^0-9]/g, ""));
                    if(!isNaN(num)) { ofertas = num; }
                }
            }
        });
        
        let imgElem = item.querySelector('img');
        let imagen = imgElem ? imgElem.src : 'N/A';
        
        let enlaceElem = item.querySelector('a');
        let enlace = enlaceElem ? enlaceElem.href : 'N/A';
        
        data.push([lote, descripcion, precio, ofertas, imagen, enlace]);
    });
    return data;
    """)

    # Agrega subasta_id a cada artículo
    articulos_con_id = []
    for art in articulos:
        articulos_con_id.append((*art, subasta_id))

    print(f"✅ Extracción completada: {len(articulos_con_id)} artículos obtenidos (subasta {subasta_id}).")
    return articulos_con_id

# =========================================
# FUNCIONES DE BASE DE DATOS
# =========================================
def update_database(articulos):
    """Actualiza la base de datos:
       - Inserta nuevos registros o actualiza precio/ofertas si han cambiado.
       - Guarda subasta_id en cada registro.
       - Registra cada inserción/actualización en la tabla historial_subastas.
    """
    conn = sqlite3.connect("subastas.db")
    cursor = conn.cursor()
    
    # Crear la tabla principal si no existe
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subastas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lote TEXT,
            descripcion TEXT,
            precio TEXT,
            ofertas INTEGER,
            imagen TEXT,
            enlace TEXT UNIQUE,
            subasta_id TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Crear la tabla historial si no existe
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historial_subastas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lote TEXT,
            descripcion TEXT,
            precio TEXT,
            ofertas INTEGER,
            imagen TEXT,
            enlace TEXT,
            subasta_id TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Cargar registros existentes (para ver si cambió precio u ofertas)
    cursor.execute("SELECT precio, ofertas, enlace FROM subastas")
    existing = {row[2]: {'precio': row[0], 'ofertas': row[1]} for row in cursor.fetchall()}
    
    for art in articulos:
        lote, descripcion, precio, ofertas, imagen, enlace, subasta_id = art
        
        if enlace in existing:
            # Si ya existe, actualizar si cambió el precio u ofertas
            if precio != existing[enlace]['precio'] or ofertas != existing[enlace]['ofertas']:
                cursor.execute('''
                    UPDATE subastas
                    SET precio = ?, ofertas = ?, subasta_id = ?, timestamp = CURRENT_TIMESTAMP
                    WHERE enlace = ?
                ''', (precio, ofertas, subasta_id, enlace))
                
                print(f"🔄 Actualizado: {enlace}, nuevo precio={precio}, ofertas={ofertas}.")
                
                # Guarda también en historial
                cursor.execute('''
                    INSERT INTO historial_subastas (lote, descripcion, precio, ofertas, imagen, enlace, subasta_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (lote, descripcion, precio, ofertas, imagen, enlace, subasta_id))
        else:
            # Insertar nuevo registro
            cursor.execute('''
                INSERT INTO subastas (lote, descripcion, precio, ofertas, imagen, enlace, subasta_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (lote, descripcion, precio, ofertas, imagen, enlace, subasta_id))
            
            print(f"➕ Insertado: {enlace}, precio={precio}, ofertas={ofertas}.")
            
            # Guarda también en historial
            cursor.execute('''
                INSERT INTO historial_subastas (lote, descripcion, precio, ofertas, imagen, enlace, subasta_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (lote, descripcion, precio, ofertas, imagen, enlace, subasta_id))
    
    conn.commit()
    conn.close()

# =========================================
# FLUJO PRINCIPAL
# =========================================
def detect_initial_articles():
    """Carga todos los artículos en la base de datos al inicio."""
    print(f"🔎 Detección inicial en {SCRAPE_URL} ...")
    articulos = scrape_subastas(SCRAPE_URL)
    if articulos:
        update_database(articulos)
        print("✅ Detección inicial completada y artículos guardados.")
    else:
        print("❌ No se encontraron artículos en la detección inicial.")

def observer_updates_limited(run_time=150, interval=60):
    """
    Observa la subasta durante 'run_time' segundos (2.5 min por defecto).
    Cada 'interval' segundos, vuelve a scrapear y actualizar.
    """
    print("🔄 Iniciando observador de actualizaciones (limitado).")
    start_time = time.time()
    
    while time.time() - start_time < run_time:
        articulos = scrape_subastas(SCRAPE_URL)
        if articulos:
            update_database(articulos)
            print("✅ Base de datos actualizada.")
        else:
            print("❌ No se encontraron artículos en esta actualización.")
        
        time.sleep(interval)
    
    print("⏹️ Observador finalizado (tiempo límite alcanzado).")

if __name__ == "__main__":
    try:
        detect_initial_articles()
        observer_updates_limited(run_time=150, interval=60)
    finally:
        driver.quit()
        print("✅ Script finalizado.")
