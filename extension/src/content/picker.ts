// Chế độ tự chọn vùng: rê chuột để viền, ↑ mở rộng ra khối cha, bấm để chọn, Esc hủy

let cleanup: (() => void) | null = null;

export function stopPicker() {
  cleanup?.();
  cleanup = null;
}

export function startPicker(onPicked: (el: HTMLElement) => void, onCancel: () => void) {
  stopPicker();
  let current: HTMLElement | null = null;

  const overlay = document.createElement('div');
  Object.assign(overlay.style, {
    position: 'fixed',
    zIndex: '2147483647',
    pointerEvents: 'none',
    border: '3px solid #2563eb',
    background: 'rgba(37,99,235,0.08)',
    borderRadius: '4px',
    display: 'none'
  } as CSSStyleDeclaration);

  const hint = document.createElement('div');
  hint.textContent = 'Bấm để chọn vùng • ↑ mở rộng vùng • Esc để hủy';
  Object.assign(hint.style, {
    position: 'fixed',
    top: '12px',
    left: '50%',
    transform: 'translateX(-50%)',
    zIndex: '2147483647',
    pointerEvents: 'none',
    background: '#1e3a8a',
    color: '#fff',
    padding: '6px 14px',
    borderRadius: '6px',
    font: '13px/1.4 system-ui, sans-serif',
    boxShadow: '0 2px 8px rgba(0,0,0,.25)'
  } as CSSStyleDeclaration);

  document.documentElement.append(overlay, hint);

  const draw = () => {
    if (!current) return;
    const r = current.getBoundingClientRect();
    Object.assign(overlay.style, {
      display: 'block',
      left: `${r.left}px`,
      top: `${r.top}px`,
      width: `${r.width}px`,
      height: `${r.height}px`
    });
  };

  const onMove = (e: MouseEvent) => {
    const t = e.target as HTMLElement;
    if (!t || t === overlay || t === hint) return;
    current = t;
    draw();
  };
  const onClick = (e: MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const el = current;
    stopPicker();
    if (el) onPicked(el);
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      stopPicker();
      onCancel();
    } else if (e.key === 'ArrowUp' && current?.parentElement && current.parentElement !== document.documentElement) {
      e.preventDefault();
      current = current.parentElement;
      draw();
    }
  };

  document.addEventListener('mousemove', onMove, true);
  document.addEventListener('click', onClick, true);
  document.addEventListener('keydown', onKey, true);
  window.addEventListener('scroll', draw, true);

  cleanup = () => {
    document.removeEventListener('mousemove', onMove, true);
    document.removeEventListener('click', onClick, true);
    document.removeEventListener('keydown', onKey, true);
    window.removeEventListener('scroll', draw, true);
    overlay.remove();
    hint.remove();
  };
}

