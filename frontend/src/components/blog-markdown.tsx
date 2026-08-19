import { Fragment, ReactNode } from 'react';

const INLINE_PATTERN = /(\[[^\]]+\]\([^)\s]+(?:\s+"[^"]*")?\)|!\[[^\]]*\]\([^)\s]+(?:\s+"[^"]*")?\))/g;

function renderInline(text: string): ReactNode[] {
  const parts = text.split(INLINE_PATTERN);
  return parts.map((part, i) => {
    const linkMatch = part.match(/^\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)$/);
    if (linkMatch) {
      const href = linkMatch[2];
      const internal = href.startsWith('/');
      return (
        <a
          key={i}
          href={href}
          target={internal ? undefined : '_blank'}
          rel={internal ? undefined : 'noopener noreferrer'}
          className="text-brand-accent-light hover:text-brand-accent underline underline-offset-4 decoration-brand-accent/40"
        >
          {renderInline(linkMatch[1])}
        </a>
      );
    }
    const imgMatch = part.match(/^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)$/);
    if (imgMatch) {
      return (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          key={i}
          src={imgMatch[2]}
          alt={imgMatch[1] || ''}
          title={imgMatch[3]}
          loading="lazy"
          className="inline-block max-h-72 rounded-xl border border-steel/15 my-2"
        />
      );
    }
    const boldParts = part.split(/(\*\*[^*]+\*\*)/g);
    return (
      <Fragment key={i}>
        {boldParts.map((bp, j) =>
          bp.startsWith('**') && bp.endsWith('**') ? (
            <strong key={j} className="text-offwhite font-semibold">
              {bp.slice(2, -2)}
            </strong>
          ) : (
            <Fragment key={j}>{bp}</Fragment>
          )
        )}
      </Fragment>
    );
  });
}

function cleanHeading(text: string) {
  return renderInline(text.replace(/#/g, '').trim());
}

export function renderMarkdown(content: string): ReactNode[] {
  const lines = content.split('\n');
  const nodes: ReactNode[] = [];
  let list: string[] = [];
  let key = 0;

  const flushList = () => {
    if (list.length) {
      nodes.push(
        <ul key={key++} className="list-disc pl-6 space-y-2 text-ice/90 leading-relaxed">
          {list.map((item, i) => (
            <li key={i}>{renderInline(item)}</li>
          ))}
        </ul>
      );
      list = [];
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flushList();
      continue;
    }
    const imgMatch = line.trim().match(/^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)$/);
    if (imgMatch) {
      flushList();
      nodes.push(
        <figure key={key++} className="my-6">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imgMatch[2]}
            alt={imgMatch[1] || ''}
            title={imgMatch[3]}
            className="w-full rounded-xl border border-steel/15"
            loading="lazy"
          />
          {imgMatch[1] && (
            <figcaption className="text-center text-xs text-text-muted mt-2 italic">
              {imgMatch[1]}
            </figcaption>
          )}
        </figure>
      );
      continue;
    }
    if (line.startsWith('###### ')) {
      flushList();
      nodes.push(
        <h6 key={key++} className="text-sm font-bold text-text-muted font-heading mt-5 mb-2 uppercase tracking-wide">
          {cleanHeading(line.slice(7))}
        </h6>
      );
    } else if (line.startsWith('##### ')) {
      flushList();
      nodes.push(
        <h5 key={key++} className="text-base font-bold text-offwhite font-heading mt-5 mb-2">
          {cleanHeading(line.slice(6))}
        </h5>
      );
    } else if (line.startsWith('#### ')) {
      flushList();
      nodes.push(
        <h4 key={key++} className="text-lg font-semibold text-offwhite font-heading mt-6 mb-2">
          {cleanHeading(line.slice(5))}
        </h4>
      );
    } else if (line.startsWith('### ')) {
      flushList();
      nodes.push(
        <h3 key={key++} className="text-xl md:text-2xl font-semibold text-offwhite font-heading mt-8 mb-3">
          {cleanHeading(line.slice(4))}
        </h3>
      );
    } else if (line.startsWith('## ')) {
      flushList();
      nodes.push(
        <h2 key={key++} className="text-2xl md:text-[1.75rem] font-bold tracking-tight text-offwhite font-heading mt-10 mb-4">
          {cleanHeading(line.slice(3))}
        </h2>
      );
    } else if (line.startsWith('# ')) {
      flushList();
      nodes.push(
        <h1 key={key++} className="text-3xl md:text-4xl font-extrabold tracking-tight text-offwhite font-heading mt-10 mb-6">
          {cleanHeading(line.slice(2))}
        </h1>
      );
    } else if (line.startsWith('> ')) {
      flushList();
      nodes.push(
        <blockquote
          key={key++}
          className="glass-card rounded-xl border-l-2 border-l-cyan-300 p-5 my-6 text-ice/90 leading-relaxed"
        >
          {renderInline(line.slice(2))}
        </blockquote>
      );
    } else if (line.startsWith('- ')) {
      list.push(line.slice(2));
    } else {
      flushList();
      nodes.push(
        <p key={key++} className="text-ice/90 leading-relaxed my-4">
          {renderInline(line)}
        </p>
      );
    }
  }
  flushList();
  return nodes;
}