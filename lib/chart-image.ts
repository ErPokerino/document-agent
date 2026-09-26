/**
 * Save an SVG chart as a PNG.
 *
 * The chart on the page is styled by classes. A detached copy does not have
 * that stylesheet, so the colours actually painted are copied onto the clone
 * before it is drawn. Two pixels per unit keeps the labels readable when the
 * file is placed in a slide.
 */

const SCALE = 2;

const COPIED = ["fill", "stroke", "stroke-width", "stroke-linejoin", "font-family", "font-size", "font-weight", "opacity"];

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function downloadText(filename: string, text: string) {
  downloadBlob(new Blob([text], { type: "text/csv;charset=utf-8" }), filename);
}

export function paperColor(): string {
  return getComputedStyle(document.documentElement).getPropertyValue("--paper").trim() || "#ffffff";
}

export function chartPaint() {
  const style = getComputedStyle(document.documentElement);
  const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    paper: read("--paper", "#ffffff"),
    ink: read("--ink", "#17211f"),
    muted: read("--muted", "#6b7773"),
    track: read("--surface-2", "#e7eeeb"),
  };
}

export function downloadSvgAsPng(svg: SVGSVGElement, filename: string, background: string): Promise<void> {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const originals = [...svg.querySelectorAll("*")];
  const copies = [...clone.querySelectorAll("*")];
  originals.forEach((node, index) => {
    const computed = getComputedStyle(node);
    const copy = copies[index] as SVGElement | undefined;
    if (!copy) return;
    for (const name of COPIED) {
      const value = computed.getPropertyValue(name);
      if (value) copy.style.setProperty(name, value);
    }
  });

  const box = svg.viewBox.baseVal;
  const width = box?.width || Number(svg.getAttribute("width")) || svg.clientWidth;
  const height = box?.height || Number(svg.getAttribute("height")) || svg.clientHeight;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  const ground = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  ground.setAttribute("width", "100%");
  ground.setAttribute("height", "100%");
  ground.setAttribute("fill", background);
  clone.insertBefore(ground, clone.firstChild);

  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], { type: "image/svg+xml;charset=utf-8" }));
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(width * SCALE);
      canvas.height = Math.round(height * SCALE);
      const context = canvas.getContext("2d");
      if (!context) {
        URL.revokeObjectURL(url);
        reject(new Error("The chart could not be drawn as an image."));
        return;
      }
      context.scale(SCALE, SCALE);
      context.drawImage(image, 0, 0, width, height);
      canvas.toBlob((blob) => {
        URL.revokeObjectURL(url);
        if (!blob) {
          reject(new Error("The chart could not be drawn as an image."));
          return;
        }
        downloadBlob(blob, filename);
        resolve();
      }, "image/png");
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("The chart could not be drawn as an image."));
    };
    image.src = url;
  });
}

export function downloadSvgMarkup(markup: string, filename: string, background: string): Promise<void> {
  const parsed = new DOMParser().parseFromString(markup, "image/svg+xml");
  const svg = parsed.documentElement;
  if (!(svg instanceof SVGSVGElement)) {
    return Promise.reject(new Error("The chart could not be drawn as an image."));
  }
  document.body.appendChild(svg);
  svg.style.position = "absolute";
  svg.style.left = "-9999px";
  return downloadSvgAsPng(svg, filename, background).finally(() => svg.remove());
}
