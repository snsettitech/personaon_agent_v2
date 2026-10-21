'use client';

import React, { useRef, useState } from 'react';
import { QRCodeSVG, QRCodeCanvas } from 'qrcode.react';

interface QRCodeDisplayProps {
  url: string;
  size?: number;
  personaName?: string;
  showDownload?: boolean;
  onDownload?: () => void;
}

export function QRCodeDisplay({ url, size = 200, personaName, showDownload = true, onDownload }: QRCodeDisplayProps) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const [downloading, setDownloading] = useState(false);

  const downloadPng = () => {
    const canvas = canvasRef.current?.querySelector('canvas') as HTMLCanvasElement | null;
    if (!canvas) return;
    setDownloading(true);
    try {
      const canvasEl = canvas;
      const link = document.createElement('a');
      const safeName = (personaName ?? 'persona').replace(/[\\/:*?"<>|]/g, '-');
      link.download = `${safeName}-qr.png`;
      link.href = canvasEl.toDataURL('image/png');
      link.click();
      onDownload?.();
    } finally {
      setTimeout(() => setDownloading(false), 1000);
    }
  };

  return (
    <div className="flex flex-col items-center gap-4">
      {/* Visible SVG QR */}
      <div className="p-4 bg-white rounded-2xl border border-[#E7E5E4] shadow-sm inline-block">
        <QRCodeSVG
          value={url}
          size={size}
          bgColor="#FFFFFF"
          fgColor="#1C1917"
          level="M"
          marginSize={1}
        />
      </div>

      {/* Hidden canvas for PNG download */}
      <div ref={canvasRef} className="sr-only" aria-hidden="true">
        <QRCodeCanvas
          value={url}
          size={512}
          bgColor="#FFFFFF"
          fgColor="#1C1917"
          level="M"
          marginSize={2}
        />
      </div>

      {showDownload && (
        <div className="flex gap-2">
          <button
            type="button"
            onClick={downloadPng}
            disabled={downloading}
            className="px-4 py-2 text-sm font-semibold bg-[#0F766E] hover:bg-[#0D9488] text-white rounded-xl transition-colors disabled:opacity-50 cursor-pointer"
          >
            {downloading ? 'Saving…' : '↓ Download PNG'}
          </button>
        </div>
      )}
    </div>
  );
}
