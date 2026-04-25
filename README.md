# Colmena BOT 🐝

Bot de Telegram que analiza archivos CSV / XLSX / XLSM como una "colmena" de mini-bots
que debaten sobre la calidad del archivo.

## Roles de la colmena

- 👁️ **Lector** — detecta estructura, hojas, filas y columnas reales.
- 🛡️ **Inspector** — pre-vuelo seguro de Excel pesado o `.xlsm` (sin ejecutar macros).
- 🧹 **Limpiador** — celdas vacías, columnas inútiles, rangos inflados.
- 🕵️ **Detective** — duplicados, fechas/correos inválidos, valores raros.
- 📊 **Analista** — métricas, totales, mínimos, máximos, promedios, categorías.
- 🔤 **Detective fino** — dobles espacios, typos, letras repetidas, correos sospechosos.
- ⚖️ **Crítico** — puntaje de salud y nivel de confianza del archivo.
- 🧠 **Jefe** — coordina la mesa y entrega el veredicto final.
- 📝 **Constructor** — genera el reporte `.txt` descargable.

## Modo seguro

- No ejecuta macros de archivos `.xlsm`.
- Limita filas, columnas y celdas analizadas (`core/limits.py`).
- Elige la hoja más probable de datos.
- Avisa si el archivo parece inflado.
- Entrega un reporte aunque no pueda analizar todo.

## Estructura

```
app.py
handlers/
    telegram_handlers.py
core/
    reader.py
    workbook_profiler.py
    analyzer.py
    text_quality.py
    report.py
    utils.py
    limits.py
```

## Cómo correrlo localmente

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="tu_token"
python app.py
```

## Cómo desplegar en Railway

1. Sube este repo a GitHub.
2. En Railway crea un nuevo proyecto desde el repo.
3. Agrega la variable `TELEGRAM_BOT_TOKEN` en *Variables*.
4. Railway lee `Procfile` y arranca el worker `python app.py`.

El bot usa *long polling*, así que no necesitas exponer un puerto público.

## Comandos del bot

- `/start` — mensaje de bienvenida y reglas de uso.
- `/ayuda` — explicación rápida de los roles.
- Subir un archivo CSV / XLSX / XLSM → la colmena lo analiza y devuelve resumen + reporte `.txt`.
