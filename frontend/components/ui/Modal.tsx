'use client';

import React, { useEffect, useRef, useCallback } from 'react';

interface ModalProps {
    isOpen: boolean;
    onClose: () => void;
    title: string;
    children: React.ReactNode;
    size?: 'sm' | 'md' | 'lg';
    'aria-describedby'?: string;
}

const sizeStyles = {
    sm: 'max-w-sm',
    md: 'max-w-md',
    lg: 'max-w-2xl',
};

// Get all focusable elements within a container
function getFocusableElements(container: HTMLElement): HTMLElement[] {
    const elements = container.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    return Array.from(elements).filter(el => !el.hasAttribute('disabled') && el.offsetParent !== null);
}

export function Modal({ isOpen, onClose, title, children, size = 'md', ...props }: ModalProps) {
    const modalRef = useRef<HTMLDivElement>(null);
    const previousActiveElement = useRef<HTMLElement | null>(null);
    const titleId = `modal-title-${title.replace(/\s+/g, '-').toLowerCase()}`;

    // Focus trap implementation
    const handleKeyDown = useCallback((e: KeyboardEvent) => {
        if (e.key === 'Escape') {
            onClose();
            return;
        }

        if (e.key !== 'Tab' || !modalRef.current) return;

        const focusable = getFocusableElements(modalRef.current);
        if (focusable.length === 0) return;

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (e.shiftKey) {
            // Shift+Tab: if on first element, move to last
            if (document.activeElement === first) {
                e.preventDefault();
                last.focus();
            }
        } else {
            // Tab: if on last element, move to first
            if (document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }
    }, [onClose]);

    useEffect(() => {
        if (isOpen) {
            // Store the currently focused element
            previousActiveElement.current = document.activeElement as HTMLElement;

            // Add event listener
            document.addEventListener('keydown', handleKeyDown);
            document.body.style.overflow = 'hidden';

            // Focus the modal or first focusable element
            requestAnimationFrame(() => {
                if (modalRef.current) {
                    const focusable = getFocusableElements(modalRef.current);
                    if (focusable.length > 0) {
                        focusable[0].focus();
                    } else {
                        modalRef.current.focus();
                    }
                }
            });
        }

        return () => {
            document.removeEventListener('keydown', handleKeyDown);
            document.body.style.overflow = 'unset';

            // Restore focus to the previously focused element
            if (previousActiveElement.current && typeof previousActiveElement.current.focus === 'function') {
                previousActiveElement.current.focus();
            }
        };
    }, [isOpen, handleKeyDown]);

    if (!isOpen) return null;

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            role="presentation"
            onClick={onClose}
            style={{ animation: 'fadeIn 0.2s ease' }}
        >
            {/* Backdrop */}
            <div
                className="absolute inset-0 bg-[rgba(8,14,26,0.75)] backdrop-blur-[6px]"
                aria-hidden="true"
                style={{ animation: 'fadeIn 0.2s ease' }}
            />

            {/* Modal Content */}
            <div
                ref={modalRef}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                aria-describedby={props['aria-describedby']}
                tabIndex={-1}
                className={`relative w-full ${sizeStyles[size]} bg-white border border-slate-200 rounded-[20px] shadow-[0_10px_30px_rgba(0,0,0,0.15),0_4px_8px_rgba(0,0,0,0.08)] outline-none`}
                onClick={(e) => e.stopPropagation()}
                style={{ animation: 'slideUp 0.3s ease' }}
            >
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
                    <h2 id={titleId} className="text-xl font-bold text-slate-900">{title}</h2>
                    <button
                        onClick={onClose}
                        aria-label="Close modal"
                        className="p-2 rounded-[10px] text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors duration-150"
                    >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>

                {/* Body */}
                <div className="px-6 py-4">
                    {children}
                </div>
            </div>
        </div>
    );
}
