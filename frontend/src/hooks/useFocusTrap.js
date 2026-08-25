import { useEffect } from 'react';

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

// 모달 등 오버레이가 열려있는 동안 Tab/Shift+Tab이 containerRef 안에서만 순환하게 만듭니다.
// 열리면 안의 첫 포커스 가능 요소로 이동시키고, 닫히면 모달을 열기 전 포커스였던 곳으로 되돌립니다.
const useFocusTrap = (containerRef, isActive) => {
  useEffect(() => {
    if (!isActive || !containerRef.current) return undefined;

    const triggerElement = document.activeElement;
    const initialFocusable = containerRef.current.querySelectorAll(FOCUSABLE_SELECTOR)[0];
    initialFocusable?.focus();

    const handleKeyDown = (event) => {
      if (event.key !== 'Tab' || !containerRef.current) return;

      const focusable = Array.from(containerRef.current.querySelectorAll(FOCUSABLE_SELECTOR));
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      triggerElement?.focus?.();
    };
  }, [isActive, containerRef]);
};

export default useFocusTrap;
