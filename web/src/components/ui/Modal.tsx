import { useRef } from "react";
import { useDismissable } from "../../lib/hooks/useDismissable";

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}

export function Modal({ isOpen, onClose, title, children }: ModalProps) {
  // The overlay click handler closes on outside-click, so we only need
  // Escape dismissal here. useDismissable also listens for outside
  // mousedown, but the dialog spans the full overlay so that's a no-op.
  const containerRef = useRef<HTMLDivElement>(null);
  useDismissable(containerRef, isOpen, onClose);

  if (!isOpen) return null;

  return (
    <div
      ref={containerRef}
      className="modal-overlay"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
    >
      <div className="modal-container">
        <div className="modal-header">
          <h2 id="modal-title">{title}</h2>
          <button
            onClick={onClose}
            className="modal-close"
            aria-label="Close dialog"
          >
            ✕
          </button>
        </div>
        <div className="modal-content">{children}</div>
      </div>
    </div>
  );
}
