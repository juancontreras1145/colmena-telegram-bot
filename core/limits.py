"""Límites seguros para no colapsar Railway con archivos pesados."""

# Tamaño máximo del archivo aceptado (bytes). 25 MB.
MAX_FILE_BYTES = 25 * 1024 * 1024

# Si el archivo supera este tamaño se considera "pesado" y entramos en modo seguro.
HEAVY_FILE_BYTES = 5 * 1024 * 1024

# Filas / columnas máximas que el analizador procesa por hoja.
MAX_ROWS = 100_000
MAX_COLS = 200

# Para archivos pesados, recortamos aún más.
SAFE_MAX_ROWS = 20_000
SAFE_MAX_COLS = 80

# Celdas máximas inspeccionadas por hoja (ancho * alto).
MAX_CELLS_PER_SHEET = 2_000_000
SAFE_MAX_CELLS_PER_SHEET = 500_000

# Hojas máximas a inspeccionar dentro de un libro Excel.
MAX_SHEETS_TO_INSPECT = 30

# Cuándo gritar "rango inflado": si las celdas reportadas por Excel son N veces
# las celdas con datos reales.
INFLATED_RANGE_RATIO = 5.0

# Cuándo gritar "archivo inflado": tamaño en bytes / celdas reales.
INFLATED_BYTES_PER_CELL = 200

# Para detección de outliers numéricos.
OUTLIER_STD_FACTOR = 6.0

# Para "muchos vacíos" en una columna.
HIGH_NULL_RATIO = 0.4

# Texto: longitud mínima para considerar repeticiones de letras sospechosas.
MIN_TEXT_LEN_FOR_REPEAT = 5
REPEAT_LETTERS_THRESHOLD = 3  # 3+ letras iguales seguidas
