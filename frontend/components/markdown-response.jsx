'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export function MarkdownResponse({ children }) {
  return (
    <div className="result-answer markdown-response">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          // Responses can contain untrusted text. Do not fetch embedded images.
          img: () => null,
          a: ({ children, href, title }) => href
            ? <a href={href} title={title} target="_blank" rel="noopener noreferrer">{children}</a>
            : <span>{children}</span>,
          table: ({ children }) => <div className="markdown-table"><table>{children}</table></div>,
        }}
      >
        {typeof children === 'string' ? children : ''}
      </ReactMarkdown>
    </div>
  );
}
