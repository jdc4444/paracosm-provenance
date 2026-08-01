"use client";

import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type WheelEvent as ReactWheelEvent,
} from "react";

const PANEL_WIDTH_STORAGE_KEY = "paracosm:right-inspector-width";
const DEFAULT_PANEL_WIDTH = 500;
const MIN_PANEL_WIDTH = 360;
const MAX_PANEL_WIDTH = 780;
const MIN_MAIN_WIDTH = 420;

type RightInspectorPanelProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  label: string;
  children: ReactNode;
  panelClassName?: string;
  contentClassName?: string;
  contentId?: string;
};

function panelWidthLimit() {
  if (typeof window === "undefined") return MAX_PANEL_WIDTH;
  return Math.max(
    MIN_PANEL_WIDTH,
    Math.min(MAX_PANEL_WIDTH, window.innerWidth - MIN_MAIN_WIDTH),
  );
}

function clampPanelWidth(width: number) {
  return Math.min(panelWidthLimit(), Math.max(MIN_PANEL_WIDTH, width));
}

export function RightInspectorPanel({
  open,
  onOpenChange,
  label,
  children,
  panelClassName = "",
  contentClassName = "",
  contentId = "right-inspector-content",
}: RightInspectorPanelProps) {
  const [panelWidth, setPanelWidth] = useState(DEFAULT_PANEL_WIDTH);
  const [resizing, setResizing] = useState(false);
  const panelWidthRef = useRef(DEFAULT_PANEL_WIDTH);
  const contentRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef({ pointerId: -1, startX: 0, startWidth: 0 });

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const savedWidth = Number.parseInt(
        window.localStorage.getItem(PANEL_WIDTH_STORAGE_KEY) || "",
        10,
      );
      if (!Number.isFinite(savedWidth)) return;
      const nextWidth = clampPanelWidth(savedWidth);
      panelWidthRef.current = nextWidth;
      setPanelWidth(nextWidth);
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onOpenChange(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onOpenChange, open]);

  function setAndPersistWidth(width: number) {
    const nextWidth = clampPanelWidth(width);
    panelWidthRef.current = nextWidth;
    setPanelWidth(nextWidth);
    window.localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, String(nextWidth));
  }

  function startResize(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Pointer capture can be unavailable for assistive or synthetic events.
    }
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: panelWidthRef.current,
    };
    setResizing(true);
  }

  function resize(event: ReactPointerEvent<HTMLDivElement>) {
    if (!resizing || dragRef.current.pointerId !== event.pointerId) return;
    const nextWidth = clampPanelWidth(
      dragRef.current.startWidth + dragRef.current.startX - event.clientX,
    );
    panelWidthRef.current = nextWidth;
    setPanelWidth(nextWidth);
  }

  function finishResize(event: ReactPointerEvent<HTMLDivElement>) {
    if (dragRef.current.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    dragRef.current.pointerId = -1;
    setResizing(false);
    window.localStorage.setItem(
      PANEL_WIDTH_STORAGE_KEY,
      String(panelWidthRef.current),
    );
  }

  function resizeFromKeyboard(event: ReactKeyboardEvent<HTMLDivElement>) {
    let nextWidth = panelWidthRef.current;
    if (event.key === "ArrowLeft") nextWidth += 24;
    else if (event.key === "ArrowRight") nextWidth -= 24;
    else if (event.key === "Home") nextWidth = MIN_PANEL_WIDTH;
    else if (event.key === "End") nextWidth = panelWidthLimit();
    else return;
    event.preventDefault();
    setAndPersistWidth(nextWidth);
  }

  function containPanelWheel(event: ReactWheelEvent<HTMLElement>) {
    const content = contentRef.current;
    if (
      !open ||
      !content ||
      event.ctrlKey ||
      Math.abs(event.deltaY) <= Math.abs(event.deltaX) ||
      !(event.target instanceof Node) ||
      !content.contains(event.target)
    ) {
      return;
    }

    const pixelDelta =
      event.deltaY *
      (event.deltaMode === 1
        ? 16
        : event.deltaMode === 2
          ? content.clientHeight
          : 1);
    let scrollTarget =
      event.target instanceof HTMLElement ? event.target : content;

    while (scrollTarget !== content) {
      const overflowY = window.getComputedStyle(scrollTarget).overflowY;
      const scrollable =
        /auto|scroll|overlay/.test(overflowY) &&
        scrollTarget.scrollHeight > scrollTarget.clientHeight + 1;
      const canScroll =
        pixelDelta < 0
          ? scrollTarget.scrollTop > 0
          : scrollTarget.scrollTop + scrollTarget.clientHeight <
            scrollTarget.scrollHeight - 1;
      if (scrollable && canScroll) break;
      scrollTarget = scrollTarget.parentElement || content;
    }

    event.preventDefault();
    event.stopPropagation();
    scrollTarget.scrollTop += pixelDelta;
  }

  const style = {
    "--right-inspector-width": `${panelWidth}px`,
  } as CSSProperties;

  return (
    <aside
      className={`right-inspector-panel ${open ? "open" : ""} ${
        resizing ? "resizing" : ""
      } ${panelClassName}`.trim()}
      style={style}
      data-panel-width={panelWidth}
      onWheel={containPanelWheel}
    >
      {open && (
        <div
          className="right-inspector-resize"
          role="separator"
          aria-label={`Resize ${label} panel`}
          aria-orientation="vertical"
          aria-valuemin={MIN_PANEL_WIDTH}
          aria-valuemax={panelWidthLimit()}
          aria-valuenow={panelWidth}
          tabIndex={0}
          onDoubleClick={() => setAndPersistWidth(DEFAULT_PANEL_WIDTH)}
          onKeyDown={resizeFromKeyboard}
          onPointerDown={startResize}
          onPointerMove={resize}
          onPointerUp={finishResize}
          onPointerCancel={finishResize}
        />
      )}
      <button
        type="button"
        className="right-inspector-toggle"
        aria-label={open ? `Collapse ${label} panel` : `Expand ${label} panel`}
        aria-expanded={open}
        aria-controls={contentId}
        onClick={() => onOpenChange(!open)}
      >
        <span aria-hidden="true">{open ? "›" : "‹"}</span>
        <b>{label}</b>
      </button>
      <div
        ref={contentRef}
        className={`right-inspector-content ${contentClassName}`.trim()}
        id={contentId}
        hidden={!open}
      >
        {children}
      </div>
    </aside>
  );
}
