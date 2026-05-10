"use client";

import { useState, useRef, useEffect, useId, KeyboardEvent } from "react";
import { getTagColorClass } from "../../lib/ui/tag-colors";

interface TagPickerProps {
  value: string[];
  onChange: (tags: string[]) => void;
  suggestions: string[];
  disabled?: boolean;
}

export function TagPicker({ value, onChange, suggestions, disabled }: TagPickerProps) {
  const [inputValue, setInputValue] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listboxId = useId();

  // Close on outside click
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [isOpen]);

  const filtered = suggestions.filter(
    (s) => s.toLowerCase().includes(inputValue.toLowerCase()) && !value.includes(s),
  );
  const showDropdown = isOpen && (filtered.length > 0 || (inputValue.trim() && !value.includes(inputValue.trim())));

  const addTag = (tag: string) => {
    const normalized = tag.trim().toLowerCase();
    if (!normalized || value.includes(normalized)) {
      setInputValue("");
      setIsOpen(false);
      return;
    }
    onChange([...value, normalized]);
    setInputValue("");
    setIsOpen(false);
    inputRef.current?.focus();
  };

  const removeTag = (tag: string) => {
    onChange(value.filter((t) => t !== tag));
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      setIsOpen(false);
      return;
    }
    if ((e.key === "Enter" || e.key === ",") && inputValue.trim()) {
      e.preventDefault();
      addTag(inputValue);
      return;
    }
    if (e.key === "Backspace" && !inputValue && value.length > 0) {
      removeTag(value[value.length - 1]);
    }
  };

  return (
    <div className="picker-container tag-picker-container" ref={containerRef}>
      <div
        className="tag-picker-field"
        onClick={() => !disabled && inputRef.current?.focus()}
      >
        {value.map((tag) => {
          return (
          <span key={tag} className={`tag-chip ${getTagColorClass(tag)}`}>
            {tag}
            {!disabled && (
              <button
                type="button"
                className="tag-chip-remove"
                aria-label={`Remove tag ${tag}`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  removeTag(tag);
                }}
              >
                ×
              </button>
            )}
          </span>
          );
        })}
        <input
          ref={inputRef}
          className="tag-picker-input"
          aria-label="Tags"
          aria-autocomplete="list"
          aria-controls={showDropdown ? listboxId : undefined}
          aria-expanded={!!showDropdown}
          type="text"
          value={inputValue}
          disabled={disabled}
          placeholder={value.length === 0 ? "Add tags…" : ""}
          autoComplete="off"
          onChange={(e) => {
            setInputValue(e.target.value);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
        />
      </div>
      {showDropdown && (
        <ul
          id={listboxId}
          className="picker-dropdown"
          role="listbox"
          aria-label="Tag suggestions"
        >
          {filtered.map((tag) => (
            <li
              key={tag}
              role="option"
              aria-selected={false}
              className="picker-option"
              onMouseDown={(e) => {
                e.preventDefault();
                addTag(tag);
              }}
            >
              {tag}
            </li>
          ))}
          {inputValue.trim() && !value.includes(inputValue.trim()) && filtered.length === 0 && (
            <li
              role="option"
              aria-selected={false}
              className="picker-option picker-create"
              onMouseDown={(e) => {
                e.preventDefault();
                addTag(inputValue);
              }}
            >
              Add &ldquo;{inputValue.trim()}&rdquo;
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
