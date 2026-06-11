"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useDismissable } from "../../lib/hooks/useDismissable";

interface SubjectPickerProps {
  value: string;
  onChange: (subject: string) => void;
  suggestions: string[];
  disabled?: boolean;
}

export function SubjectPicker({ value, onChange, suggestions, disabled }: SubjectPickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [inputValue, setInputValue] = useState(value);
  const [editing, setEditing] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listboxId = useId();

  // Sync with external value changes (e.g. note switch)
  useEffect(() => {
    setInputValue(value);
    setEditing(false);
  }, [value]);

  // Auto-focus the input whenever edit mode is entered
  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  // Close dropdown (and exit edit mode) on Escape or outside click.
  const dismiss = useCallback(() => {
    setIsOpen(false);
    setEditing(false);
  }, []);
  useDismissable(containerRef, isOpen || editing, dismiss);

  const filtered = suggestions.filter(
    (s) => s.toLowerCase().includes(inputValue.toLowerCase()) && s !== inputValue,
  );
  const showDropdown =
    isOpen &&
    (filtered.length > 0 ||
      (inputValue.trim() && !suggestions.includes(inputValue.trim())));

  const commit = (subject: string) => {
    const trimmed = subject.trim();
    setInputValue(trimmed);
    onChange(trimmed);
    setIsOpen(false);
    setEditing(false);
  };

  // Display mode — show badge or placeholder
  if (!editing) {
    return (
      <div className="picker-container" ref={containerRef}>
        {value ? (
          <button
            type="button"
            className="subject-badge"
            disabled={disabled}
            onClick={() => setEditing(true)}
          >
            {value}
          </button>
        ) : (
          <button
            type="button"
            className="subject-placeholder"
            disabled={disabled}
            onClick={() => setEditing(true)}
          >
            Add subject…
          </button>
        )}
      </div>
    );
  }

  // Edit mode — text input with autocomplete dropdown
  return (
    <div className="picker-container" ref={containerRef}>
      <input
        ref={inputRef}
        className="note-editor-input picker-input"
        aria-label="Subject"
        aria-autocomplete="list"
        aria-controls={showDropdown ? listboxId : undefined}
        aria-expanded={!!showDropdown}
        type="text"
        value={inputValue}
        disabled={disabled}
        placeholder="inbox"
        autoComplete="off"
        onChange={(e) => {
          setInputValue(e.target.value);
          onChange(e.target.value);
          setIsOpen(true);
        }}
        onFocus={() => setIsOpen(true)}
        onBlur={() => {
          // Delay so onMouseDown on a dropdown option fires first
          setTimeout(() => setEditing(false), 150);
        }}
        onKeyDown={(e) => {
          // Escape is handled by useDismissable above.
          if (e.key === "Enter" && inputValue.trim()) {
            e.preventDefault();
            commit(inputValue);
          }
        }}
      />
      {showDropdown && (
        <ul
          id={listboxId}
          className="picker-dropdown"
          role="listbox"
          aria-label="Subject suggestions"
        >
          {filtered.map((subject) => (
            <li
              key={subject}
              role="option"
              aria-selected={false}
              className="picker-option"
              onMouseDown={(e) => {
                e.preventDefault();
                commit(subject);
              }}
            >
              {subject}
            </li>
          ))}
          {inputValue.trim() &&
            !suggestions.includes(inputValue.trim()) &&
            filtered.length === 0 && (
              <li
                role="option"
                aria-selected={false}
                className="picker-option picker-create"
                onMouseDown={(e) => {
                  e.preventDefault();
                  commit(inputValue);
                }}
              >
                Use &ldquo;{inputValue.trim()}&rdquo;
              </li>
            )}
        </ul>
      )}
    </div>
  );
}
