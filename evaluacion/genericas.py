"""Palabras genéricas de E2c (lista cerrada aprobada; 198 palabras normalizadas).

Una clave de anotación es válida solo con al menos una palabra que no está en esta lista,
que no es solo dígitos y de 3 caracteres o más. Cambiar la lista requiere aprobación: su
hash está fijado en `tests/unit/test_eval_conjuntos.py` (G-0).

Grupos: gramaticales (41), pedido y cortesía (47, las de T4 de D93), números escritos (54, los de
T3 de D93), unidades físicas (21) y unidades comerciales (36); «sobre» está en dos grupos.
"""

PALABRAS_GENERICAS: tuple[str, ...] = (
    "a", "ademas", "agrega", "agregame", "agregueme", "al", "anota", "anotame", "anoteme", "ante",
    "apunta", "apuntame", "apunteme", "bolsa", "bolsas", "bolsita", "bolsitas", "botella", "botellas",
    "botellita", "botellitas", "buenas", "buenos", "caja", "cajas", "cajita", "cajitas", "catorce",
    "cc", "cien", "ciento", "cinco", "cincuenta", "con", "cuarenta", "cuarto", "cuatro",
    "cuatrocientos", "dame", "de", "del", "deme", "desde", "dias", "diecinueve", "dieciocho",
    "dieciseis", "diecisiete", "diez", "display", "displays", "doce", "docena", "docenas", "dos",
    "doscientos", "e", "el", "en", "encargo", "entre", "enviame", "envieme", "fardito", "farditos",
    "fardo", "fardos", "favor", "g", "gr", "gracias", "gramo", "gramos", "grs", "hola", "kg", "kilo",
    "kilos", "l", "la", "las", "lata", "latas", "latita", "latitas", "lb", "lbs", "le", "les", "libra",
    "libras", "litro", "litros", "lo", "los", "lt", "lts", "manda", "mandame", "mandar", "mandarme",
    "mande", "mandeme", "me", "media", "medio", "mejor", "mi", "mil", "mililitro", "mililitros", "mis",
    "mitad", "ml", "muchas", "necesito", "ni", "novecientos", "noventa", "nueve", "o", "ochenta",
    "ocho", "ochocientos", "once", "paquete", "paquetes", "paquetito", "paquetitos", "par", "para",
    "podria", "pongame", "ponme", "por", "porfa", "porfis", "puede", "puedes", "que", "quiero",
    "quince", "quinientos", "quintal", "quintales", "rollo", "rollos", "se", "sean", "seis",
    "seiscientos", "sesenta", "setecientos", "setenta", "siete", "sin", "sobre", "sobrecito",
    "sobrecitos", "sobres", "solamente", "solo", "son", "su", "sus", "tambien", "tardes", "te",
    "tercio", "trae", "traeme", "traigame", "trece", "treinta", "tres", "trescientos", "tu", "tus",
    "u", "un", "una", "unas", "unidad", "unidades", "uno", "unos", "veinte", "veinticinco",
    "veinticuatro", "veintidos", "veintinueve", "veintiocho", "veintiseis", "veintisiete",
    "veintitres", "veintiuno", "y", "ya",
)

GENERICAS: frozenset[str] = frozenset(PALABRAS_GENERICAS)
