// Ghi nhớ vị trí từng đoạn trên trang thật (không sửa DOM gốc)

export type Anchor =
  | { kind: 'element'; el: HTMLElement }
  | { kind: 'segment'; nodes: Node[] }; // đoạn ảo cắt theo <br> (trang truyện)

export const anchors = new Map<string, Anchor>();
export const transEls = new Map<string, HTMLElement>();

export function anchorRange(a: Anchor): Range | null {
  const r = document.createRange();
  try {
    if (a.kind === 'element') {
      if (!a.el.isConnected) return null;
      r.selectNodeContents(a.el);
    } else {
      const first = a.nodes[0];
      const last = a.nodes[a.nodes.length - 1];
      if (!first?.isConnected || !last?.isConnected) return null;
      r.setStartBefore(first);
      r.setEndAfter(last);
    }
    return r;
  } catch {
    return null;
  }
}

export function anchorElement(a: Anchor): Element | null {
  if (a.kind === 'element') return a.el;
  const n = a.nodes[0];
  return n ? (n.nodeType === 1 ? (n as Element) : n.parentElement) : null;
}

export function resetAnchors() {
  transEls.forEach((x) => x.remove());
  transEls.clear();
  anchors.forEach((a) => {
    if (a.kind === 'element') a.el.removeAttribute('data-tts-orig');
  });
  anchors.clear();
  const hl = (CSS as any).highlights;
  if (hl) {
    hl.delete('tts-preview');
    hl.delete('tts-reading');
  }
  document.documentElement.removeAttribute('data-tts-hide');
}

