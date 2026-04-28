"""Analizador estático de APK para Colmena BOT.

No ejecuta la aplicación. Solo abre el APK como ZIP, extrae metadatos básicos,
busca indicadores de riesgo y genera un reporte seguro para Telegram.
"""
from __future__ import annotations

import hashlib
import os
import re
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .utils import human_size, now_str, truncate

URL_RE = re.compile(rb"https?://[A-Za-z0-9./?&_%=:#@+~;-]+", re.IGNORECASE)
DOMAIN_RE = re.compile(
    rb"\b(?:[a-zA-Z0-9-]{1,63}\.)+(?:com|net|org|io|cl|app|dev|cloud|xyz|top|site|online|me|co|ai|gg|ru|cn|br|ar|pe|es|info|biz)\b",
    re.IGNORECASE,
)
IP_RE = re.compile(rb"\b(?:\d{1,3}\.){3}\d{1,3}\b")
PERMISSION_RE = re.compile(rb"android\.permission\.[A-Z0-9_]+")
PACKAGE_RE = re.compile(rb"[a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z][a-zA-Z0-9_]*){2,}")

SENSITIVE_PERMISSIONS: Dict[str, str] = {
    "android.permission.READ_SMS": "Lee SMS",
    "android.permission.SEND_SMS": "Envía SMS",
    "android.permission.RECEIVE_SMS": "Recibe SMS",
    "android.permission.READ_CONTACTS": "Lee contactos",
    "android.permission.WRITE_CONTACTS": "Modifica contactos",
    "android.permission.GET_ACCOUNTS": "Lee cuentas del dispositivo",
    "android.permission.RECORD_AUDIO": "Usa micrófono",
    "android.permission.CAMERA": "Usa cámara",
    "android.permission.ACCESS_FINE_LOCATION": "Ubicación precisa",
    "android.permission.ACCESS_COARSE_LOCATION": "Ubicación aproximada",
    "android.permission.ACCESS_BACKGROUND_LOCATION": "Ubicación en segundo plano",
    "android.permission.READ_CALL_LOG": "Lee historial de llamadas",
    "android.permission.WRITE_CALL_LOG": "Modifica historial de llamadas",
    "android.permission.CALL_PHONE": "Puede iniciar llamadas",
    "android.permission.READ_PHONE_STATE": "Lee estado/identificadores del teléfono",
    "android.permission.READ_EXTERNAL_STORAGE": "Lee almacenamiento externo",
    "android.permission.WRITE_EXTERNAL_STORAGE": "Escribe almacenamiento externo",
    "android.permission.MANAGE_EXTERNAL_STORAGE": "Acceso amplio a archivos",
    "android.permission.SYSTEM_ALERT_WINDOW": "Dibuja encima de otras apps",
    "android.permission.REQUEST_INSTALL_PACKAGES": "Puede pedir instalar APKs",
    "android.permission.BIND_ACCESSIBILITY_SERVICE": "Servicio de accesibilidad",
    "android.permission.QUERY_ALL_PACKAGES": "Lista otras apps instaladas",
    "android.permission.POST_NOTIFICATIONS": "Envía notificaciones",
    "android.permission.FOREGROUND_SERVICE": "Servicios activos en primer plano",
}

COMMON_TRACKERS: Dict[str, str] = {
    "firebase": "Firebase / Google",
    "google-analytics": "Google Analytics",
    "googlesyndication": "Google Ads",
    "doubleclick": "Google DoubleClick",
    "facebook": "Meta / Facebook SDK",
    "crashlytics": "Crashlytics",
    "appsflyer": "AppsFlyer",
    "adjust": "Adjust",
    "onesignal": "OneSignal",
    "amplitude": "Amplitude",
    "mixpanel": "Mixpanel",
    "sentry": "Sentry",
    "branch": "Branch.io",
    "admob": "AdMob",
}

FRAMEWORK_HINTS: Dict[str, Tuple[str, ...]] = {
    "Flutter": ("libflutter.so", "flutter_assets/", "io.flutter"),
    "React Native": ("libreactnativejni.so", "index.android.bundle", "com.facebook.react"),
    "Unity": ("libunity.so", "assets/bin/Data/", "com.unity3d"),
    "Cordova/Ionic": ("cordova.js", "www/", "org.apache.cordova"),
    "Xamarin/.NET MAUI": ("assemblies/", "libmonodroid", "xamarin"),
    "Godot": ("libgodot", "godot"),
}

RISK_WEIGHTS = {
    "critical_perm": 18,
    "sensitive_perm": 8,
    "http_url": 10,
    "private_ip": 5,
    "native_lib": 6,
    "dex_many": 5,
    "install_packages": 18,
    "accessibility": 20,
    "debuggable_hint": 12,
    "suspicious_file": 12,
    "many_domains": 8,
}

CRITICAL_PERMISSIONS = {
    "android.permission.BIND_ACCESSIBILITY_SERVICE",
    "android.permission.REQUEST_INSTALL_PACKAGES",
    "android.permission.MANAGE_EXTERNAL_STORAGE",
    "android.permission.SYSTEM_ALERT_WINDOW",
    "android.permission.READ_SMS",
    "android.permission.SEND_SMS",
    "android.permission.RECEIVE_SMS",
    "android.permission.ACCESS_BACKGROUND_LOCATION",
    "android.permission.QUERY_ALL_PACKAGES",
}

SUSPICIOUS_FILE_PATTERNS = (
    "frida",
    "xposed",
    "substrate",
    "magisk",
    "su",
    "busybox",
    "payload",
    "metasploit",
    "rat",
)


@dataclass
class ApkFinding:
    severity: str
    title: str
    detail: str
    action: str


@dataclass
class ApkAnalysis:
    file_name: str
    file_size: int
    sha256: str
    md5: str
    zip_ok: bool
    total_files: int = 0
    dex_files: List[str] = field(default_factory=list)
    native_libs: List[str] = field(default_factory=list)
    certificates: List[str] = field(default_factory=list)
    manifest_present: bool = False
    manifest_is_binary: bool = False
    package_candidates: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    sensitive_permissions: Dict[str, str] = field(default_factory=dict)
    urls: List[str] = field(default_factory=list)
    domains: List[str] = field(default_factory=list)
    ips: List[str] = field(default_factory=list)
    trackers: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    suspicious_files: List[str] = field(default_factory=list)
    largest_files: List[Tuple[str, int]] = field(default_factory=list)
    findings: List[ApkFinding] = field(default_factory=list)
    risk_score: int = 0
    risk_label: str = "Bajo"
    notes: List[str] = field(default_factory=list)


def _read_bytes_limited(path: str, limit: int = 80 * 1024 * 1024) -> bytes:
    """Lee bytes hasta un máximo razonable para buscar strings sin fundir memoria."""
    chunks: List[bytes] = []
    total = 0
    with open(path, "rb") as f:
        while total < limit:
            data = f.read(min(1024 * 1024, limit - total))
            if not data:
                break
            chunks.append(data)
            total += len(data)
    return b"\n".join(chunks)


def _hash_file(path: str) -> Tuple[str, str]:
    sha = hashlib.sha256()
    md5 = hashlib.md5()  # noqa: S324 - solo identificación, no seguridad criptográfica.
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(chunk)
            md5.update(chunk)
    return sha.hexdigest(), md5.hexdigest()


def _decode_set(matches: List[bytes], limit: int = 120) -> List[str]:
    values = sorted({m.decode("utf-8", errors="ignore").strip(" ./\t\r\n\x00") for m in matches})
    return [v for v in values if v][:limit]


def _is_probably_binary_xml(data: bytes) -> bool:
    # AndroidManifest.xml dentro de APK normal suele ser AXML binario.
    if not data:
        return False
    if data.startswith(b"<?xml") or b"<manifest" in data[:500]:
        return False
    return b"manifest" in data.lower() or b"android.permission" in data


def _private_or_local_ip(ip: str) -> bool:
    parts = ip.split(".")
    try:
        nums = [int(x) for x in parts]
    except ValueError:
        return False
    if any(n > 255 for n in nums):
        return False
    return (
        nums[0] == 10
        or nums[0] == 127
        or (nums[0] == 192 and nums[1] == 168)
        or (nums[0] == 172 and 16 <= nums[1] <= 31)
    )


def _detect_frameworks(file_names: List[str], blob_lower: str) -> List[str]:
    joined = "\n".join(file_names).lower()
    found: List[str] = []
    for framework, hints in FRAMEWORK_HINTS.items():
        for hint in hints:
            h = hint.lower()
            if h in joined or h in blob_lower:
                found.append(framework)
                break
    return sorted(set(found))


def _detect_trackers(domains: List[str], blob_lower: str) -> List[str]:
    found: List[str] = []
    domain_text = "\n".join(domains).lower()
    for key, label in COMMON_TRACKERS.items():
        if key in domain_text or key in blob_lower:
            found.append(label)
    return sorted(set(found))


def _risk_label(score: int) -> str:
    if score >= 70:
        return "Alto"
    if score >= 35:
        return "Medio"
    return "Bajo"


def analyze_apk(path: str, file_name: Optional[str] = None) -> ApkAnalysis:
    """Analiza un APK de forma estática y devuelve hallazgos resumibles."""
    name = file_name or os.path.basename(path)
    size = os.path.getsize(path)
    sha256, md5 = _hash_file(path)

    result = ApkAnalysis(
        file_name=name,
        file_size=size,
        sha256=sha256,
        md5=md5,
        zip_ok=False,
    )

    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad:
                result.notes.append(f"ZIP/APK tiene una entrada dañada: {bad}")
            result.zip_ok = True
            infos = zf.infolist()
            result.total_files = len(infos)
            file_names = [i.filename for i in infos]
            lower_names = [x.lower() for x in file_names]
            result.dex_files = [x for x in file_names if x.lower().endswith(".dex")]
            result.native_libs = [x for x in file_names if x.lower().endswith(".so")]
            result.certificates = [x for x in file_names if x.upper().startswith("META-INF/") and x.upper().endswith((".RSA", ".DSA", ".EC", ".SF"))]
            result.largest_files = sorted(
                [(i.filename, i.file_size) for i in infos], key=lambda t: t[1], reverse=True
            )[:10]
            result.manifest_present = "androidmanifest.xml" in lower_names

            suspicious: List[str] = []
            for original, lower in zip(file_names, lower_names):
                base = os.path.basename(lower)
                if any(p in base for p in SUSPICIOUS_FILE_PATTERNS):
                    suspicious.append(original)
            result.suspicious_files = suspicious[:40]

            manifest_bytes = b""
            if result.manifest_present:
                try:
                    manifest_bytes = zf.read("AndroidManifest.xml")
                    result.manifest_is_binary = _is_probably_binary_xml(manifest_bytes)
                except Exception as exc:  # noqa: BLE001
                    result.notes.append(f"No pude leer AndroidManifest.xml: {exc}")

            # Escaneo liviano: nombres de archivos + Manifest + DEX + recursos chicos.
            scan_parts: List[bytes] = ["\n".join(file_names).encode("utf-8", errors="ignore")]
            if manifest_bytes:
                scan_parts.append(manifest_bytes)

            bytes_budget = 14 * 1024 * 1024
            used = sum(len(p) for p in scan_parts)
            for info in infos:
                lname = info.filename.lower()
                if used >= bytes_budget:
                    break
                if info.file_size > 3 * 1024 * 1024:
                    continue
                if lname.endswith((".dex", ".xml", ".json", ".txt", ".properties", ".html", ".js", ".bundle", ".arsc")):
                    try:
                        data = zf.read(info.filename)
                    except Exception:  # noqa: BLE001
                        continue
                    scan_parts.append(data)
                    used += len(data)

            blob = b"\n".join(scan_parts)
            blob_lower = blob.decode("utf-8", errors="ignore").lower()

            result.permissions = _decode_set(PERMISSION_RE.findall(blob), limit=180)
            result.sensitive_permissions = {
                p: SENSITIVE_PERMISSIONS[p]
                for p in result.permissions
                if p in SENSITIVE_PERMISSIONS
            }
            result.urls = _decode_set(URL_RE.findall(blob), limit=120)
            result.domains = _decode_set(DOMAIN_RE.findall(blob), limit=180)
            raw_ips = _decode_set(IP_RE.findall(blob), limit=120)
            result.ips = [ip for ip in raw_ips if all(0 <= int(part) <= 255 for part in ip.split("."))]
            packages = _decode_set(PACKAGE_RE.findall(blob), limit=220)
            result.package_candidates = [p for p in packages if not p.startswith("android.permission")][:80]
            result.frameworks = _detect_frameworks(file_names, blob_lower)
            result.trackers = _detect_trackers(result.domains, blob_lower)

    except zipfile.BadZipFile:
        result.findings.append(
            ApkFinding(
                "critico",
                "El archivo no parece un APK válido",
                "Un APK debe poder abrirse como ZIP. Este archivo falló esa validación.",
                "No instalar. Verifica origen y extensión real del archivo.",
            )
        )
        result.risk_score = 90
        result.risk_label = "Alto"
        return result

    score = 0

    if not result.manifest_present:
        score += 25
        result.findings.append(
            ApkFinding(
                "alto",
                "No encontré AndroidManifest.xml",
                "Un APK normal debería incluir AndroidManifest.xml.",
                "Tratar como archivo sospechoso o incompleto.",
            )
        )

    critical = [p for p in result.sensitive_permissions if p in CRITICAL_PERMISSIONS]
    if critical:
        score += min(45, len(critical) * RISK_WEIGHTS["critical_perm"])
        result.findings.append(
            ApkFinding(
                "alto",
                "Permisos sensibles críticos",
                ", ".join(f"{p} ({result.sensitive_permissions[p]})" for p in critical[:8]),
                "Instalar solo si confías totalmente en el origen y entiendes por qué pide esos permisos.",
            )
        )

    regular_sensitive = [p for p in result.sensitive_permissions if p not in CRITICAL_PERMISSIONS]
    if regular_sensitive:
        score += min(35, len(regular_sensitive) * RISK_WEIGHTS["sensitive_perm"])
        result.findings.append(
            ApkFinding(
                "medio",
                "Permisos sensibles",
                ", ".join(f"{p} ({result.sensitive_permissions[p]})" for p in regular_sensitive[:10]),
                "Comparar permisos con la función real de la app.",
            )
        )

    http_urls = [u for u in result.urls if u.lower().startswith("http://")]
    if http_urls:
        score += min(30, len(http_urls) * RISK_WEIGHTS["http_url"])
        result.findings.append(
            ApkFinding(
                "medio",
                "URLs sin HTTPS",
                "; ".join(http_urls[:8]),
                "Preferir apps que usen HTTPS. Revisar si transmiten datos sensibles.",
            )
        )

    private_ips = [ip for ip in result.ips if _private_or_local_ip(ip)]
    if private_ips:
        score += min(20, len(private_ips) * RISK_WEIGHTS["private_ip"])
        result.findings.append(
            ApkFinding(
                "bajo",
                "IPs locales o privadas encontradas",
                ", ".join(private_ips[:12]),
                "Puede ser normal en desarrollo, pero raro en apps públicas.",
            )
        )

    if result.native_libs:
        score += min(18, RISK_WEIGHTS["native_lib"] + len(result.native_libs) // 12)
        result.findings.append(
            ApkFinding(
                "bajo",
                "Incluye librerías nativas .so",
                f"Encontré {len(result.native_libs)} archivo(s) nativo(s).",
                "No es malo por sí solo, pero reduce la visibilidad del análisis estático simple.",
            )
        )

    if len(result.dex_files) > 1:
        score += min(16, RISK_WEIGHTS["dex_many"] + len(result.dex_files))
        result.findings.append(
            ApkFinding(
                "bajo",
                "APK multidex",
                f"Encontré {len(result.dex_files)} archivo(s) .dex.",
                "Normal en apps grandes; revisar junto con permisos y dominios.",
            )
        )

    if result.suspicious_files:
        score += min(35, RISK_WEIGHTS["suspicious_file"] + len(result.suspicious_files) * 2)
        result.findings.append(
            ApkFinding(
                "alto",
                "Nombres de archivos sospechosos",
                "; ".join(result.suspicious_files[:10]),
                "Revisar manualmente. Un nombre sospechoso no confirma malware, pero amerita cautela.",
            )
        )

    if len(result.domains) >= 20:
        score += RISK_WEIGHTS["many_domains"]
        result.findings.append(
            ApkFinding(
                "medio",
                "Muchos dominios embebidos",
                f"Encontré {len(result.domains)} dominio(s).",
                "Revisar si pertenecen a servicios esperables o a terceros desconocidos.",
            )
        )

    if "debuggable=true" in blob_lower or "android:debuggable=\"true\"" in blob_lower:
        score += RISK_WEIGHTS["debuggable_hint"]
        result.findings.append(
            ApkFinding(
                "medio",
                "Posible modo debug",
                "Aparece una señal textual de debuggable=true.",
                "No usar en producción si es una app propia. Si es ajena, sospechar de build no final.",
            )
        )

    if not result.certificates:
        score += 12
        result.findings.append(
            ApkFinding(
                "medio",
                "No vi certificados en META-INF",
                "APK moderno puede usar esquemas nuevos, pero normalmente hay trazas de firma.",
                "Verificar firma con apksigner si necesitas certeza.",
            )
        )

    result.risk_score = max(0, min(100, score))
    result.risk_label = _risk_label(result.risk_score)
    return result


def build_apk_report(analysis: ApkAnalysis, txt_path: str) -> List[str]:
    """Genera TXT completo y devuelve líneas cortas para Telegram."""
    summary = [
        f"📦 APK: {analysis.file_name}",
        f"📏 Tamaño: {human_size(analysis.file_size)}",
        f"🧬 SHA256: {analysis.sha256[:16]}...",
        f"🩺 Riesgo estático: {analysis.risk_score}/100 — {analysis.risk_label}",
        f"📄 Archivos internos: {analysis.total_files}",
        f"🔐 Permisos detectados: {len(analysis.permissions)}",
        f"⚠️ Permisos sensibles: {len(analysis.sensitive_permissions)}",
        f"🌐 URLs: {len(analysis.urls)} · Dominios: {len(analysis.domains)} · IPs: {len(analysis.ips)}",
    ]
    if analysis.frameworks:
        summary.append("🧱 Framework probable: " + ", ".join(analysis.frameworks[:4]))
    if analysis.trackers:
        summary.append("📡 Trackers/SDK posibles: " + ", ".join(analysis.trackers[:6]))
    if analysis.findings:
        summary.append(f"🔎 Hallazgos: {len(analysis.findings)}")
        for finding in analysis.findings[:6]:
            summary.append(f"- {finding.title}: {truncate(finding.detail, 130)}")

    out: List[str] = []
    p = out.append
    p("=" * 72)
    p("🐝 COLMENA APK — ANÁLISIS ESTÁTICO")
    p("=" * 72)
    p(f"Generado:       {now_str()}")
    p(f"Archivo:        {analysis.file_name}")
    p(f"Tamaño:         {human_size(analysis.file_size)}")
    p(f"ZIP válido:     {'sí' if analysis.zip_ok else 'no'}")
    p(f"SHA256:         {analysis.sha256}")
    p(f"MD5:            {analysis.md5}")
    p(f"Riesgo:         {analysis.risk_score}/100 — {analysis.risk_label}")
    p("")
    p("NOTA: este análisis es estático. No ejecuta el APK y no prueba comportamiento en tiempo real.")
    p("")

    p("--- Estructura ---")
    p(f"Archivos internos:       {analysis.total_files}")
    p(f"AndroidManifest.xml:     {'sí' if analysis.manifest_present else 'no'}")
    p(f"Manifest binario AXML:   {'sí' if analysis.manifest_is_binary else 'no'}")
    p(f"DEX encontrados:         {len(analysis.dex_files)}")
    for x in analysis.dex_files[:20]:
        p(f"  · {x}")
    p(f"Librerías nativas .so:   {len(analysis.native_libs)}")
    for x in analysis.native_libs[:30]:
        p(f"  · {x}")
    p(f"Firmas/certificados:     {len(analysis.certificates)}")
    for x in analysis.certificates[:20]:
        p(f"  · {x}")
    p("")

    if analysis.frameworks:
        p("--- Frameworks detectados ---")
        for x in analysis.frameworks:
            p(f"  · {x}")
        p("")

    p("--- Permisos ---")
    if analysis.permissions:
        for perm in analysis.permissions:
            extra = f" — {analysis.sensitive_permissions[perm]}" if perm in analysis.sensitive_permissions else ""
            p(f"  · {perm}{extra}")
    else:
        p("  No detecté permisos por búsqueda de strings. Si el Manifest está muy binario/ofuscado, conviene usar apktool/androguard.")
    p("")

    p("--- Red: URLs ---")
    if analysis.urls:
        for u in analysis.urls[:120]:
            p(f"  · {u}")
    else:
        p("  Sin URLs visibles.")
    p("")

    p("--- Red: dominios ---")
    if analysis.domains:
        for d in analysis.domains[:180]:
            p(f"  · {d}")
    else:
        p("  Sin dominios visibles.")
    p("")

    if analysis.ips:
        p("--- Red: IPs ---")
        for ip in analysis.ips[:120]:
            p(f"  · {ip}")
        p("")

    if analysis.trackers:
        p("--- Trackers/SDK posibles ---")
        for t in analysis.trackers:
            p(f"  · {t}")
        p("")

    if analysis.package_candidates:
        p("--- Paquetes/clases candidatos ---")
        for pkg in analysis.package_candidates[:80]:
            p(f"  · {pkg}")
        p("")

    if analysis.suspicious_files:
        p("--- Archivos con nombres sospechosos ---")
        for sf in analysis.suspicious_files[:40]:
            p(f"  · {sf}")
        p("")

    p("--- Archivos más pesados ---")
    for fname, fsize in analysis.largest_files:
        p(f"  · {human_size(fsize):>10}  {fname}")
    p("")

    p("--- Hallazgos ---")
    if not analysis.findings:
        p("  No encontré hallazgos fuertes. Igual verifica el origen antes de instalar.")
    else:
        for f in analysis.findings:
            p(f"[{f.severity.upper()}] {f.title}")
            p(f"  detalle: {f.detail}")
            p(f"  acción:  {f.action}")
            p("")

    if analysis.notes:
        p("--- Notas técnicas ---")
        for n in analysis.notes:
            p(f"  · {n}")
        p("")

    p("--- Recomendación final ---")
    if analysis.risk_label == "Alto":
        p("No instalar salvo que sea una app propia o de origen totalmente confiable. Revisar permisos, dominios y firma.")
    elif analysis.risk_label == "Medio":
        p("Instalar con cautela. Los hallazgos no prueban malware, pero sí justifican revisar origen y permisos.")
    else:
        p("Riesgo estático bajo. Aun así, un APK desconocido nunca debe tratarse como 100% seguro solo por análisis estático.")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))

    return summary
