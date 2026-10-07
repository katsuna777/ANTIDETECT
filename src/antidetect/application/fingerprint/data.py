"""Pure fingerprint building blocks (no I/O, no randomness).

Everything a coherent machine is assembled from lives here: GPUs with the
exact strings current Chrome prints, per-graphics-backend WebGL capability
tables, screens expressed in CSS pixels with the OS chrome insets, and
CPU/RAM classes. The generator draws from these pools; the stealth layer reads
the capability tables to make a spoofed GPU report limits that match it.

Strings follow what Chrome >= 130 really reports (ANGLE format with the PCI
device id on Windows, ``ANGLE Metal Renderer`` on macOS).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

PLATFORMS = ("windows", "macos", "linux")


def host_platform() -> str:
    """OS the app is running on, in the same vocabulary as profile platforms."""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return "linux"


# --------------------------------------------------------------------- GPUs

@dataclass(frozen=True)
class Gpu:
    vendor: str          # UNMASKED_VENDOR_WEBGL
    renderer: str        # UNMASKED_RENDERER_WEBGL
    family: str          # graphics backend: "d3d11" | "metal" | "gl"
    label: str           # short human name for the UI
    weight: int = 1      # relative market share inside its OS pool


def _win(vendor: str, name: str, device_id: int, weight: int, label: str) -> Gpu:
    return Gpu(
        f"Google Inc. ({vendor})",
        f"ANGLE ({vendor}, {name} (0x{device_id:08X}) Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "d3d11",
        label,
        weight,
    )


def _mac(chip: str, weight: int) -> Gpu:
    return Gpu(
        "Google Inc. (Apple)",
        f"ANGLE (Apple, ANGLE Metal Renderer: {chip}, Unspecified Version)",
        "metal",
        chip,
        weight,
    )


GPUS: dict[str, tuple[Gpu, ...]] = {
    "windows": (
        _win("NVIDIA", "NVIDIA GeForce GTX 1650", 0x1F82, 10, "GTX 1650"),
        _win("NVIDIA", "NVIDIA GeForce GTX 1660 SUPER", 0x21C4, 5, "GTX 1660 SUPER"),
        _win("NVIDIA", "NVIDIA GeForce GTX 1060 6GB", 0x1C03, 6, "GTX 1060"),
        _win("NVIDIA", "NVIDIA GeForce RTX 2060", 0x1F08, 6, "RTX 2060"),
        _win("NVIDIA", "NVIDIA GeForce RTX 3050", 0x2507, 5, "RTX 3050"),
        _win("NVIDIA", "NVIDIA GeForce RTX 3060", 0x2504, 10, "RTX 3060"),
        _win("NVIDIA", "NVIDIA GeForce RTX 3060 Laptop GPU", 0x2560, 6, "RTX 3060 Laptop"),
        _win("NVIDIA", "NVIDIA GeForce RTX 3070", 0x2484, 5, "RTX 3070"),
        _win("NVIDIA", "NVIDIA GeForce RTX 4060", 0x2882, 7, "RTX 4060"),
        _win("NVIDIA", "NVIDIA GeForce RTX 4070", 0x2786, 4, "RTX 4070"),
        _win("Intel", "Intel(R) UHD Graphics 630", 0x3E9B, 12, "UHD 630"),
        _win("Intel", "Intel(R) UHD Graphics", 0x9A49, 8, "UHD (11th gen)"),
        _win("Intel", "Intel(R) Iris(R) Xe Graphics", 0x46A6, 8, "Iris Xe"),
        _win("AMD", "AMD Radeon RX 580 Series", 0x67DF, 4, "RX 580"),
        _win("AMD", "AMD Radeon RX 6600", 0x73FF, 4, "RX 6600"),
        _win("AMD", "AMD Radeon(TM) Graphics", 0x1638, 5, "Radeon Graphics"),
    ),
    "macos": (
        _mac("Apple M1", 12),
        _mac("Apple M1 Pro", 5),
        _mac("Apple M2", 9),
        _mac("Apple M2 Pro", 4),
        _mac("Apple M3", 7),
        _mac("Apple M3 Pro", 3),
        _mac("Apple M4", 6),
    ),
    "linux": (
        Gpu(
            "Google Inc. (Intel)",
            "ANGLE (Intel, Mesa Intel(R) UHD Graphics 630 (CFL GT2), OpenGL 4.6)",
            "gl", "UHD 630", 8,
        ),
        Gpu(
            "Google Inc. (NVIDIA Corporation)",
            "ANGLE (NVIDIA Corporation, NVIDIA GeForce GTX 1060 6GB/PCIe/SSE2, "
            "OpenGL 4.5.0 NVIDIA 535.154.05)",
            "gl", "GTX 1060", 5,
        ),
        Gpu(
            "Google Inc. (AMD)",
            "ANGLE (AMD, AMD Radeon RX 580 Series (radeonsi, polaris10, LLVM 15.0.7, "
            "DRM 3.54, 6.2.0-39-generic), OpenGL 4.6 (Core Profile) Mesa 23.2.1)",
            "gl", "RX 580", 3,
        ),
    ),
}

#: Apple chip -> (physical cores, ram choices in GB). Cores/RAM/GPU of one
#: Mac must come from the same row.
MAC_CHIPS: dict[str, tuple[tuple[int, ...], tuple[int, ...]]] = {
    "Apple M1": ((8,), (8, 16)),
    "Apple M1 Pro": ((8, 10), (16, 32)),
    "Apple M2": ((8,), (8, 16, 24)),
    "Apple M2 Pro": ((10, 12), (16, 32)),
    "Apple M3": ((8,), (8, 16, 24)),
    "Apple M3 Pro": ((11, 12), (18, 36)),
    "Apple M4": ((10,), (16, 24, 32)),
}

#: (cores, ram GB) pools for non-Apple machines.
PC_HARDWARE: dict[str, tuple[tuple[int, int], ...]] = {
    "windows": ((4, 8), (6, 8), (6, 16), (8, 8), (8, 16), (12, 16), (12, 32), (16, 32), (20, 32)),
    "linux": ((4, 8), (8, 8), (8, 16), (12, 16), (16, 32)),
}

# ------------------------------------------------------- WebGL capability sets
# Numeric GL enums -> value. {"f32": [...]} / {"i32": [...]} mark typed arrays.
_E = {
    "MAX_TEXTURE_SIZE": 0x0D33,
    "MAX_CUBE_MAP_TEXTURE_SIZE": 0x851C,
    "MAX_RENDERBUFFER_SIZE": 0x84E8,
    "MAX_VERTEX_ATTRIBS": 0x8869,
    "MAX_VERTEX_UNIFORM_VECTORS": 0x8DFB,
    "MAX_VARYING_VECTORS": 0x8DFC,
    "MAX_COMBINED_TEXTURE_IMAGE_UNITS": 0x8B4D,
    "MAX_VERTEX_TEXTURE_IMAGE_UNITS": 0x8B4C,
    "MAX_TEXTURE_IMAGE_UNITS": 0x8872,
    "MAX_FRAGMENT_UNIFORM_VECTORS": 0x8DFD,
    "ALIASED_LINE_WIDTH_RANGE": 0x846E,
    "ALIASED_POINT_SIZE_RANGE": 0x846D,
    "MAX_VIEWPORT_DIMS": 0x0D3A,
    "MAX_3D_TEXTURE_SIZE": 0x8073,
    "MAX_ARRAY_TEXTURE_LAYERS": 0x88FF,
    "MAX_COLOR_ATTACHMENTS": 0x8CDF,
    "MAX_COMBINED_UNIFORM_BLOCKS": 0x8A2E,
    "MAX_DRAW_BUFFERS": 0x8824,
    "MAX_ELEMENTS_INDICES": 0x80E9,
    "MAX_ELEMENTS_VERTICES": 0x80E8,
    "MAX_FRAGMENT_UNIFORM_BLOCKS": 0x8A2D,
    "MAX_FRAGMENT_UNIFORM_COMPONENTS": 0x8B49,
    "MAX_UNIFORM_BLOCK_SIZE": 0x8A30,
    "MAX_UNIFORM_BUFFER_BINDINGS": 0x8A2F,
    "MAX_VERTEX_UNIFORM_BLOCKS": 0x8A2B,
    "MAX_VERTEX_UNIFORM_COMPONENTS": 0x8B4A,
    "MAX_TEXTURE_LOD_BIAS": 0x84FD,
}


def _table(values: dict[str, object]) -> dict[str, object]:
    out: dict[str, object] = {}
    for name, value in values.items():
        out[str(_E[name])] = value
    return out


_WEBGL1_COMMON = {
    "MAX_TEXTURE_SIZE": 16384,
    "MAX_CUBE_MAP_TEXTURE_SIZE": 16384,
    "MAX_RENDERBUFFER_SIZE": 16384,
    "MAX_VERTEX_ATTRIBS": 16,
    "MAX_VERTEX_TEXTURE_IMAGE_UNITS": 16,
    "MAX_TEXTURE_IMAGE_UNITS": 16,
    "MAX_FRAGMENT_UNIFORM_VECTORS": 1024,
    "MAX_COMBINED_TEXTURE_IMAGE_UNITS": 32,
    "ALIASED_LINE_WIDTH_RANGE": {"f32": [1, 1]},
}

#: Per graphics backend. ``metal`` values were measured on a real Apple
#: Silicon Mac running Chrome 154; ``d3d11`` is the ANGLE/D3D11 profile every
#: Windows GPU of the feature-level-11 era reports.
GL_PARAMS: dict[str, dict[str, dict[str, object]]] = {
    "metal": {
        "webgl": _table({
            **_WEBGL1_COMMON,
            "MAX_VERTEX_UNIFORM_VECTORS": 1024,
            "MAX_VARYING_VECTORS": 30,
            "ALIASED_POINT_SIZE_RANGE": {"f32": [1, 511]},
            "MAX_VIEWPORT_DIMS": {"i32": [16384, 16384]},
        }),
        "webgl2": _table({
            **_WEBGL1_COMMON,
            "MAX_VERTEX_UNIFORM_VECTORS": 1024,
            "MAX_VARYING_VECTORS": 30,
            "ALIASED_POINT_SIZE_RANGE": {"f32": [1, 511]},
            "MAX_VIEWPORT_DIMS": {"i32": [16384, 16384]},
            "MAX_3D_TEXTURE_SIZE": 2048,
            "MAX_ARRAY_TEXTURE_LAYERS": 2048,
            "MAX_COLOR_ATTACHMENTS": 8,
            "MAX_COMBINED_UNIFORM_BLOCKS": 32,
            "MAX_DRAW_BUFFERS": 8,
            "MAX_ELEMENTS_INDICES": 2147483647,
            "MAX_ELEMENTS_VERTICES": 2147483647,
            "MAX_FRAGMENT_UNIFORM_BLOCKS": 16,
            "MAX_FRAGMENT_UNIFORM_COMPONENTS": 4096,
            "MAX_UNIFORM_BLOCK_SIZE": 16384,
            "MAX_UNIFORM_BUFFER_BINDINGS": 32,
            "MAX_VERTEX_UNIFORM_BLOCKS": 16,
            "MAX_VERTEX_UNIFORM_COMPONENTS": 4096,
        }),
    },
    "d3d11": {
        "webgl": _table({
            **_WEBGL1_COMMON,
            "MAX_VERTEX_UNIFORM_VECTORS": 4095,
            "MAX_VARYING_VECTORS": 30,
            "ALIASED_POINT_SIZE_RANGE": {"f32": [1, 1024]},
            "MAX_VIEWPORT_DIMS": {"i32": [32767, 32767]},
        }),
        "webgl2": _table({
            **_WEBGL1_COMMON,
            "MAX_VERTEX_UNIFORM_VECTORS": 4095,
            "MAX_VARYING_VECTORS": 30,
            "ALIASED_POINT_SIZE_RANGE": {"f32": [1, 1024]},
            "MAX_VIEWPORT_DIMS": {"i32": [32767, 32767]},
            "MAX_3D_TEXTURE_SIZE": 2048,
            "MAX_ARRAY_TEXTURE_LAYERS": 2048,
            "MAX_COLOR_ATTACHMENTS": 8,
            "MAX_COMBINED_UNIFORM_BLOCKS": 24,
            "MAX_DRAW_BUFFERS": 8,
            "MAX_ELEMENTS_INDICES": 150000,
            "MAX_ELEMENTS_VERTICES": 1048575,
            "MAX_FRAGMENT_UNIFORM_BLOCKS": 12,
            "MAX_UNIFORM_BLOCK_SIZE": 65536,
            "MAX_UNIFORM_BUFFER_BINDINGS": 72,
            "MAX_VERTEX_UNIFORM_BLOCKS": 12,
            "MAX_VERTEX_UNIFORM_COMPONENTS": 16384,
        }),
    },
    "gl": {
        "webgl": _table({
            **_WEBGL1_COMMON,
            "MAX_VERTEX_UNIFORM_VECTORS": 4096,
            "MAX_VARYING_VECTORS": 32,
            "ALIASED_POINT_SIZE_RANGE": {"f32": [1, 2047]},
            "MAX_VIEWPORT_DIMS": {"i32": [16384, 16384]},
        }),
        "webgl2": _table({
            **_WEBGL1_COMMON,
            "MAX_VERTEX_UNIFORM_VECTORS": 4096,
            "MAX_VARYING_VECTORS": 32,
            "ALIASED_POINT_SIZE_RANGE": {"f32": [1, 2047]},
            "MAX_VIEWPORT_DIMS": {"i32": [16384, 16384]},
        }),
    },
}

# Extension sets. Metal is the measured Apple Silicon list; Direct3D11 drops the
# mobile/Apple texture formats and the GL-only polygon mode extension.
_METAL_WEBGL1 = (
    "ANGLE_instanced_arrays", "EXT_blend_minmax", "EXT_clip_control",
    "EXT_color_buffer_half_float", "EXT_depth_clamp", "EXT_disjoint_timer_query",
    "EXT_float_blend", "EXT_frag_depth", "EXT_polygon_offset_clamp", "EXT_sRGB",
    "EXT_shader_texture_lod", "EXT_texture_compression_bptc",
    "EXT_texture_compression_rgtc", "EXT_texture_filter_anisotropic",
    "EXT_texture_mirror_clamp_to_edge", "KHR_parallel_shader_compile",
    "OES_element_index_uint", "OES_fbo_render_mipmap", "OES_standard_derivatives",
    "OES_texture_float", "OES_texture_float_linear", "OES_texture_half_float",
    "OES_texture_half_float_linear", "OES_vertex_array_object",
    "WEBGL_blend_func_extended", "WEBGL_color_buffer_float",
    "WEBGL_compressed_texture_astc", "WEBGL_compressed_texture_etc",
    "WEBGL_compressed_texture_etc1", "WEBGL_compressed_texture_pvrtc",
    "WEBGL_compressed_texture_s3tc", "WEBGL_compressed_texture_s3tc_srgb",
    "WEBGL_debug_renderer_info", "WEBGL_debug_shaders", "WEBGL_depth_texture",
    "WEBGL_draw_buffers", "WEBGL_lose_context", "WEBGL_multi_draw",
    "WEBGL_polygon_mode",
)
_METAL_WEBGL2 = (
    "EXT_clip_control", "EXT_color_buffer_float", "EXT_color_buffer_half_float",
    "EXT_conservative_depth", "EXT_depth_clamp", "EXT_disjoint_timer_query_webgl2",
    "EXT_float_blend", "EXT_polygon_offset_clamp", "EXT_render_snorm",
    "EXT_texture_compression_bptc", "EXT_texture_compression_rgtc",
    "EXT_texture_filter_anisotropic", "EXT_texture_mirror_clamp_to_edge",
    "EXT_texture_norm16", "KHR_parallel_shader_compile",
    "NV_shader_noperspective_interpolation", "OES_draw_buffers_indexed",
    "OES_sample_variables", "OES_shader_multisample_interpolation",
    "OES_texture_float_linear", "WEBGL_blend_func_extended",
    "WEBGL_clip_cull_distance", "WEBGL_compressed_texture_astc",
    "WEBGL_compressed_texture_etc", "WEBGL_compressed_texture_etc1",
    "WEBGL_compressed_texture_pvrtc", "WEBGL_compressed_texture_s3tc",
    "WEBGL_compressed_texture_s3tc_srgb", "WEBGL_debug_renderer_info",
    "WEBGL_debug_shaders", "WEBGL_lose_context", "WEBGL_multi_draw",
    "WEBGL_polygon_mode", "WEBGL_provoking_vertex",
    "WEBGL_render_shared_exponent", "WEBGL_stencil_texturing",
)
_MOBILE_ONLY = {
    "WEBGL_compressed_texture_astc", "WEBGL_compressed_texture_etc",
    "WEBGL_compressed_texture_etc1", "WEBGL_compressed_texture_pvrtc",
    "WEBGL_polygon_mode",
}


def _without(names: tuple[str, ...], drop: set[str]) -> list[str]:
    return [name for name in names if name not in drop]


GL_EXTENSIONS: dict[str, dict[str, list[str]]] = {
    "metal": {"webgl": list(_METAL_WEBGL1), "webgl2": list(_METAL_WEBGL2)},
    "d3d11": {
        "webgl": _without(_METAL_WEBGL1, _MOBILE_ONLY),
        "webgl2": _without(_METAL_WEBGL2, _MOBILE_ONLY),
    },
    "gl": {
        "webgl": _without(_METAL_WEBGL1, _MOBILE_ONLY | {"EXT_clip_control", "EXT_depth_clamp"}),
        "webgl2": _without(_METAL_WEBGL2, _MOBILE_ONLY | {"EXT_clip_control", "EXT_depth_clamp"}),
    },
}


def host_gl_family() -> str:
    """Graphics backend ANGLE uses on this machine."""
    return {"macos": "metal", "windows": "d3d11", "linux": "gl"}[host_platform()]


# ------------------------------------------------------------------- screens

@dataclass(frozen=True)
class Screen:
    """A display as the page sees it: CSS pixels plus the device pixel ratio."""

    width: int
    height: int
    dpr: float
    weight: int = 1
    #: pixels the OS reserves at the top (macOS menu bar / notch)
    inset_top: int = 0
    #: pixels the OS reserves at the bottom (Windows taskbar / macOS dock)
    inset_bottom: int = 0

    @property
    def avail_width(self) -> int:
        return self.width

    @property
    def avail_height(self) -> int:
        return self.height - self.inset_top - self.inset_bottom

    @property
    def avail_top(self) -> int:
        return self.inset_top


def _w(width: int, height: int, dpr: float, weight: int, taskbar: int = 40) -> Screen:
    return Screen(width, height, dpr, weight, 0, taskbar)


def _m(width: int, height: int, dpr: float, weight: int, top: int = 25, dock: int = 0) -> Screen:
    return Screen(width, height, dpr, weight, top, dock)


SCREENS: dict[str, tuple[Screen, ...]] = {
    "windows": (
        _w(1920, 1080, 1.0, 34),
        _w(1536, 864, 1.25, 16),
        _w(1366, 768, 1.0, 12),
        _w(1440, 900, 1.0, 5),
        _w(1600, 900, 1.0, 5),
        _w(1280, 720, 1.5, 4),
        _w(2560, 1440, 1.0, 9),
        _w(1707, 960, 1.5, 5),
        _w(1920, 1080, 1.0, 3),
        _w(2048, 1152, 1.25, 3),
        _w(2560, 1440, 1.5, 2),
    ),
    "macos": (
        _m(1440, 900, 2.0, 12, 25),
        _m(1512, 982, 2.0, 18, 38),
        _m(1470, 956, 2.0, 14, 38),
        _m(1728, 1117, 2.0, 12, 38),
        _m(1680, 1050, 2.0, 5, 25),
        _m(1920, 1080, 1.0, 8, 25),
        _m(2560, 1440, 1.0, 5, 25),
        _m(2240, 1260, 2.0, 3, 25),
    ),
    "linux": (
        Screen(1920, 1080, 1.0, 10, 27, 0),
        Screen(1366, 768, 1.0, 5, 27, 0),
        Screen(2560, 1440, 1.0, 4, 27, 0),
        Screen(1536, 864, 1.25, 3, 27, 0),
    ),
}

# --------------------------------------------------------------- OS versions

#: Chrome's UA-CH ``platformVersion`` per OS (Windows 10 / 11, macOS, Linux).
PLATFORM_VERSIONS: dict[str, tuple[str, ...]] = {
    "windows": ("10.0.0", "15.0.0", "15.0.0", "19.0.0"),
    "macos": ("13.6.0", "14.5.0", "14.6.1", "15.1.0"),
    "linux": ("6.5.0", "6.8.0"),
}

UA_OS_TOKENS: dict[str, str] = {
    "windows": "Windows NT 10.0; Win64; x64",
    "macos": "Macintosh; Intel Mac OS X 10_15_7",
    "linux": "X11; Linux x86_64",
}

NAVIGATOR_PLATFORM: dict[str, str] = {
    "windows": "Win32",
    "macos": "MacIntel",
    "linux": "Linux x86_64",
}

HINTS_PLATFORM: dict[str, str] = {
    "windows": "Windows",
    "macos": "macOS",
    "linux": "Linux",
}

# ------------------------------------------------------------------ helpers


def pick_weighted(rng, items):
    """Weighted choice over objects exposing ``.weight``."""
    total = sum(max(1, getattr(item, "weight", 1)) for item in items)
    point = rng.uniform(0, total)
    upto = 0.0
    for item in items:
        upto += max(1, getattr(item, "weight", 1))
        if point <= upto:
            return item
    return items[-1]


def family_for_renderer(renderer: str | None, platform: str | None) -> str:
    """Graphics backend implied by a stored WebGL renderer string."""
    text = renderer or ""
    if "Direct3D" in text or "D3D11" in text:
        return "d3d11"
    if "Metal" in text:
        return "metal"
    if "OpenGL" in text or "Mesa" in text:
        return "gl"
    return {"windows": "d3d11", "macos": "metal", "linux": "gl"}.get(platform or "", host_gl_family())


# WebGPU names the adapter on its own (``adapter.info``), separately from WebGL: a profile
# that claims an NVIDIA card in WebGL but answers ``apple / metal-3`` there is caught at once.
# Chrome fills ``vendor`` / ``architecture`` from the PCI ids and hides ``device`` /
# ``description`` (empty strings), so only these two need a value.
_NVIDIA_ARCH = (            # first match wins: (name fragments, Dawn architecture name)
    (("RTX 40",), "lovelace"),
    (("RTX 30",), "ampere"),
    (("RTX 20", "GTX 16"), "turing"),
    (("GTX 10",), "pascal"),
)
_INTEL_ARCH = (
    (("Iris(R) Xe", "UHD Graphics 7", "Arc", "0x00009A49"), "gen-12lp"),   # 0x9A49 = Tiger Lake UHD
    (("UHD Graphics 630", "UHD Graphics 6", "HD Graphics"), "gen-9"),
)
_AMD_ARCH = (
    (("RX 580", "RX 570", "RX 480"), "gcn-4"),     # before "RX 5": the 5xx cards are Polaris, not RDNA
    (("RX 7",), "rdna-3"),
    (("RX 6",), "rdna-2"),
    (("RX 5",), "rdna-1"),
    (("Vega", "Radeon(TM) Graphics"), "gcn-5"),
)


def _arch_from(table, text: str, fallback: str) -> str:
    for fragments, arch in table:
        if any(fragment in text for fragment in fragments):
            return arch
    return fallback


def webgpu_info(renderer: str | None, platform: str | None) -> dict[str, str]:
    """``vendor`` / ``architecture`` WebGPU reports for a stored WebGL renderer string."""
    text = renderer or ""
    low = text.lower()
    if "apple" in low or "metal" in low or platform == "macos":
        return {"vendor": "apple", "architecture": "metal-3"}
    if "nvidia" in low:
        return {"vendor": "nvidia", "architecture": _arch_from(_NVIDIA_ARCH, text, "turing")}
    if "intel" in low:
        return {"vendor": "intel", "architecture": _arch_from(_INTEL_ARCH, text, "gen-9")}
    if "amd" in low or "radeon" in low:
        return {"vendor": "amd", "architecture": _arch_from(_AMD_ARCH, text, "gcn-5")}
    return {"vendor": "", "architecture": ""}


#: Chrome ``--force-color-profile`` values. It decides ``(color-gamut)`` and ``(dynamic-range)``
#: natively (measured: srgb -> gamut srgb + standard range; the host's P3/HDR display no longer
#: shows through). ``screen.colorDepth`` is not affected by it and is patched in the payload.
COLOR_PROFILE_SRGB = "srgb"
COLOR_PROFILE_P3 = "display-p3-d65"


def default_color_depth(platform: str | None, dpr: float | None) -> int:
    """What a display of this kind reports: a Mac's retina panel is wide-gamut (30), the rest 24."""
    return 30 if platform == "macos" and (dpr or 1) >= 2 else 24


def color_profile(color_depth: int | None) -> str:
    """30-bit panels are the wide-gamut (P3) ones; everything else is plain sRGB."""
    return COLOR_PROFILE_P3 if (color_depth or 24) >= 30 else COLOR_PROFILE_SRGB


# ----------------------------------------------------------------- geography

#: Representative city coordinates per supported timezone (for the geolocation
#: override, so ``navigator.geolocation`` agrees with the timezone/proxy).
TIMEZONE_COORDS: dict[str, tuple[float, float]] = {
    "America/New_York": (40.7128, -74.0060),
    "America/Chicago": (41.8781, -87.6298),
    "America/Denver": (39.7392, -104.9903),
    "America/Los_Angeles": (34.0522, -118.2437),
    "America/Sao_Paulo": (-23.5505, -46.6333),
    "America/Toronto": (43.6532, -79.3832),
    "America/Mexico_City": (19.4326, -99.1332),
    "America/Argentina/Buenos_Aires": (-34.6037, -58.3816),
    "Europe/London": (51.5074, -0.1278),
    "Europe/Berlin": (52.5200, 13.4050),
    "Europe/Paris": (48.8566, 2.3522),
    "Europe/Madrid": (40.4168, -3.7038),
    "Europe/Rome": (41.9028, 12.4964),
    "Europe/Amsterdam": (52.3676, 4.9041),
    "Europe/Warsaw": (52.2297, 21.0122),
    "Europe/Moscow": (55.7558, 37.6173),
    "Asia/Yekaterinburg": (56.8389, 60.6057),
    "Europe/Kyiv": (50.4501, 30.5234),
    "Europe/Istanbul": (41.0082, 28.9784),
    "Europe/Prague": (50.0755, 14.4378),
    "Europe/Stockholm": (59.3293, 18.0686),
    "Europe/Helsinki": (60.1699, 24.9384),
    "Europe/Copenhagen": (55.6761, 12.5683),
    "Europe/Bucharest": (44.4268, 26.1025),
    "Europe/Budapest": (47.4979, 19.0402),
    "Europe/Zurich": (47.3769, 8.5417),
    "Europe/Vienna": (48.2082, 16.3738),
    "Europe/Brussels": (50.8503, 4.3517),
    "Europe/Dublin": (53.3498, -6.2603),
    "Europe/Lisbon": (38.7223, -9.1393),
    "Europe/Athens": (37.9838, 23.7275),
    "Europe/Oslo": (59.9139, 10.7522),
    "Europe/Bratislava": (48.1486, 17.1077),
    "Europe/Sofia": (42.6977, 23.3219),
    "Asia/Tokyo": (35.6762, 139.6503),
    "Asia/Shanghai": (31.2304, 121.4737),
    "Asia/Seoul": (37.5665, 126.9780),
    "Asia/Almaty": (43.2220, 76.8512),
    "Asia/Kolkata": (22.5726, 88.3639),
    "Asia/Singapore": (1.3521, 103.8198),
    "Australia/Sydney": (-33.8688, 151.2093),
}


# --------------------------------------------------------------------- fonts

#: Characteristic system fonts per OS. Only used to mask a *foreign* OS's fonts
#: (hide what the host has but the claimed OS lacks; fake what the claimed OS
#: has but the host lacks). Fonts shared by both OSes are deliberately absent.
FONTS: dict[str, tuple[str, ...]] = {
    "windows": (
        "Segoe UI", "Segoe UI Light", "Segoe UI Semibold", "Segoe UI Symbol",
        "Segoe UI Emoji", "Segoe UI Historic", "Segoe Print", "Segoe Script",
        "Segoe MDL2 Assets", "Calibri", "Calibri Light", "Cambria", "Cambria Math",
        "Candara", "Consolas", "Constantia", "Corbel", "Ebrima", "Franklin Gothic Medium",
        "Gabriola", "Gadugi", "Ink Free", "Javanese Text", "Leelawadee UI",
        "Lucida Console", "Lucida Sans Unicode", "Malgun Gothic", "Marlett",
        "Microsoft Himalaya", "Microsoft JhengHei", "Microsoft New Tai Lue",
        "Microsoft PhagsPa", "Microsoft Sans Serif", "Microsoft Tai Le",
        "Microsoft YaHei", "Microsoft Yi Baiti", "MingLiU-ExtB", "Mongolian Baiti",
        "MS Gothic", "MS PGothic", "MS UI Gothic", "MV Boli", "Myanmar Text",
        "Nirmala UI", "Palatino Linotype", "Sitka Text", "SimSun", "Sylfaen",
        "Yu Gothic", "HoloLens MDL2 Assets",
    ),
    "macos": (
        "Helvetica Neue", "Menlo", "Monaco", "Geneva", "Lucida Grande", "Avenir",
        "Avenir Next", "American Typewriter", "Apple Chancery", "Apple Color Emoji",
        "Apple SD Gothic Neo", "Arial Hebrew", "Arial Rounded MT Bold", "Baskerville",
        "Big Caslon", "Bodoni 72", "Bradley Hand", "Chalkboard", "Chalkboard SE",
        "Chalkduster", "Cochin", "Copperplate", "Didot", "Futura", "Gill Sans",
        "Herculanum", "Hoefler Text", "Marker Felt", "Optima", "Palatino", "Papyrus",
        "Phosphate", "PingFang SC", "PingFang TC", "PingFang HK", "Rockwell",
        "Skia", "STIXGeneral", "Zapfino", "Noteworthy", "SignPainter", "Snell Roundhand",
        "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Kohinoor Devanagari", "Mishafi",
        "Luminari", "Trattatello", "Impact Condensed",
    ),
    "linux": (
        "DejaVu Sans", "DejaVu Sans Mono", "DejaVu Serif", "Liberation Sans",
        "Liberation Serif", "Liberation Mono", "Ubuntu", "Ubuntu Mono", "Cantarell",
        "Noto Sans", "Noto Serif", "Noto Mono", "Droid Sans", "FreeSans", "FreeSerif",
        "FreeMono", "Nimbus Sans", "Nimbus Roman", "Nimbus Mono PS", "Lato", "Roboto",
        "Open Sans",
    ),
}

#: Installed-on-every-OS web-safe fonts used as stand-ins for faked fonts. They
#: are picked for metrics that differ from the generic baselines (a detector
#: only sees "installed" when the width differs from the fallback's).
_SUBSTITUTES_SANS = ("Tahoma", "Verdana", "Trebuchet MS")
_SUBSTITUTES_SERIF = ("Georgia", "Palatino Linotype", "Palatino")
_SUBSTITUTES_MONO = ("Menlo", "Consolas", "Lucida Console", "Andale Mono", "DejaVu Sans Mono")
_MONO_HINTS = ("Mono", "Console", "Courier", "Consolas", "Menlo", "Monaco")
_SERIF_HINTS = ("Cambria", "Constantia", "Sylfaen", "Palatino", "Georgia", "Didot",
                "Baskerville", "Cochin", "Hoefler", "Times", "Serif", "Roman", "Caslon", "Bodoni")


def font_mask(target: str, host: str) -> dict[str, list] | None:
    """Fonts to hide / fake so ``target`` looks like the installed OS.

    ``None`` when the claimed OS is the host OS (nothing to mask).
    """
    if target == host or target not in FONTS or host not in FONTS:
        return None
    wanted, present = set(FONTS[target]), set(FONTS[host])
    hide = [name for name in FONTS[host] if name not in wanted]
    fake: list[list[str]] = []
    for name in FONTS[target]:
        if name in present:
            continue
        lower = name.lower()
        if any(h.lower() in lower for h in _MONO_HINTS):
            subs = _SUBSTITUTES_MONO
        elif any(h.lower() in lower for h in _SERIF_HINTS):
            subs = _SUBSTITUTES_SERIF
        else:
            subs = _SUBSTITUTES_SANS
        fake.append([name, ",".join(subs)])
    return {"hide": hide, "fake": fake}
