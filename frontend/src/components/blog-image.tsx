'use client';

import { useState } from 'react';

interface BlogImageProps {
  src: string;
  alt: string;
  wrapperClassName?: string;
  imgClassName?: string;
  overlayClassName?: string;
}

export function BlogImage({ src, alt, wrapperClassName, imgClassName, overlayClassName }: BlogImageProps) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <div className={wrapperClassName}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={alt} className={imgClassName} onError={() => setFailed(true)} />
      {overlayClassName && <div className={overlayClassName} aria-hidden="true" />}
    </div>
  );
}