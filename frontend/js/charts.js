/**
 * SYSFIX — Lightweight Native SVG Charts & Sparklines
 * Fully theme-aware, responsive, GPU-accelerated, and dependency-free.
 */

function getActiveThemeAccent() {
  const isLight = document.documentElement.getAttribute("data-theme") === "light";
  return isLight ? "#4F46E5" : "#7C83FF";
}

function getActiveThemeTrack() {
  const isLight = document.documentElement.getAttribute("data-theme") === "light";
  return isLight ? "#E2E8F0" : "#171923";
}

function createSparkline(data, width = 140, height = 36, color = null) {
  const strokeColor = color || getActiveThemeAccent();

  if (!data || data.length < 2) {
    return `<svg width="${width}" height="${height}" role="img" aria-label="Usage trend sparkline" style="opacity: 0.35"><line x1="0" y1="${height/2}" x2="${width}" y2="${height/2}" stroke="${strokeColor}" stroke-dasharray="3,3"/></svg>`;
  }

  const min = Math.min(...data, 0);
  const max = Math.max(...data, 100);
  const range = (max - min) || 1;

  const step = width / (data.length - 1);
  const points = data.map((val, idx) => {
    const x = idx * step;
    const y = height - ((val - min) / range) * (height - 6) - 3;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const pathStr = `M ` + points.join(' L ');
  const areaStr = `${pathStr} L ${width},${height} L 0,${height} Z`;
  const gradId = `sparkgrad_${strokeColor.replace(/[^a-zA-Z0-9]/g, '')}_${Math.floor(Math.random() * 10000)}`;

  return `
    <svg width="${width}" height="${height}" role="img" aria-label="Usage trend chart" style="overflow: visible;">
      <defs>
        <linearGradient id="${gradId}" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="${strokeColor}" stop-opacity="0.35"/>
          <stop offset="100%" stop-color="${strokeColor}" stop-opacity="0.0"/>
        </linearGradient>
      </defs>
      <path d="${areaStr}" fill="url(#${gradId})"/>
      <path d="${pathStr}" fill="none" stroke="${strokeColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
  `;
}

function createDonutGauge(percent, size = 64, strokeWidth = 6, color = null, trackColor = null) {
  const activeColor = color || getActiveThemeAccent();
  const activeTrack = trackColor || getActiveThemeTrack();
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const safePercent = Math.min(Math.max(percent || 0, 0), 100);
  const offset = circumference - (safePercent / 100) * circumference;

  return `
    <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img" aria-label="${safePercent}% gauge">
      <circle cx="${size/2}" cy="${size/2}" r="${radius}" fill="none" stroke="${activeTrack}" stroke-width="${strokeWidth}" />
      <circle cx="${size/2}" cy="${size/2}" r="${radius}" fill="none" stroke="${activeColor}" stroke-width="${strokeWidth}"
        stroke-dasharray="${circumference}" stroke-dashoffset="${offset}"
        stroke-linecap="round"
        transform="rotate(-90 ${size/2} ${size/2})" style="transition: stroke-dashoffset 0.4s ease, stroke 0.25s ease;" />
    </svg>
  `;
}
