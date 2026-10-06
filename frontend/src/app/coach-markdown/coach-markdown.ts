import { Component, computed, input, output, ViewEncapsulation } from '@angular/core';
import DOMPurify from 'dompurify';
import { Marked } from 'marked';
import { Chess } from 'chess.js';

import { RecommendedMove } from '../models/analysis';
import { BoardMove } from '../models/game';
import { CoachReference, parseCoachReference } from './coach-reference';

interface CoachReferenceToken {
  marker: string;
  source: string;
  reference: CoachReference;
}

@Component({
  selector: 'app-coach-markdown',
  template: `
    <div
      class="coach-markdown"
      [innerHTML]="html()"
      (click)="onClick($event)"
      (mouseover)="onMouseOver($event)"
      (mouseout)="onMouseOut($event)"
      (focusin)="onFocusIn($event)"
      (focusout)="onFocusOut($event)"
    ></div>
  `,
  styleUrl: './coach-markdown.css',
  encapsulation: ViewEncapsulation.None,
})
export class CoachMarkdownComponent {
  private readonly markdown = new Marked({
    breaks: true,
    gfm: true,
    renderer: {
      html: () => '',
    },
  });

  readonly text = input('');
  readonly moves = input<RecommendedMove[]>([]);
  readonly fen = input('');
  readonly legalMoves = input<string[]>([]);
  readonly movePreview = output<BoardMove | null>();
  readonly squarePreview = output<string | null>();
  readonly moveRequested = output<BoardMove>();
  readonly lineRequested = output<BoardMove[]>();

  readonly html = computed(() => this.render(this.text()));

  onClick(event: MouseEvent): void {
    const target = this.referenceLink(event.target);
    if (!target) {
      return;
    }

    const move = this.moveFromTarget(target);
    if (move) {
      event.preventDefault();
      this.moveRequested.emit(move);
      return;
    }

    const line = this.lineFromTarget(target);
    if (line) {
      event.preventDefault();
      this.lineRequested.emit(line);
      return;
    }

    const square = this.squareFromTarget(target);
    if (square) {
      event.preventDefault();
      this.squarePreview.emit(square);
    }
  }

  onMouseOver(event: MouseEvent): void {
    this.previewFromTarget(this.referenceLink(event.target));
  }

  onMouseOut(event: MouseEvent): void {
    const link = this.referenceLink(event.target);
    if (this.isInsideLink(event.relatedTarget, link)) {
      return;
    }
    if (link) {
      this.clearPreview(link);
    }
  }

  onFocusIn(event: FocusEvent): void {
    this.previewFromTarget(this.referenceLink(event.target));
  }

  onFocusOut(event: FocusEvent): void {
    const link = this.referenceLink(event.target);
    if (this.isInsideLink(event.relatedTarget, link)) {
      return;
    }
    if (link) {
      this.clearPreview(link);
    }
  }

  private render(text: string): string {
    if (!text.trim()) {
      return '';
    }

    const tokens = this.buildTokens(text);
    const withMarkers = tokens.reduce(
      (value, token) => value.replace(token.source, token.marker),
      text,
    );
    const rendered = this.markdown.parse(withMarkers) as string;
    const sanitized = DOMPurify.sanitize(rendered, {
      ALLOWED_TAGS: [
        'a',
        'blockquote',
        'br',
        'code',
        'em',
        'h1',
        'h2',
        'h3',
        'h4',
        'li',
        'ol',
        'p',
        'pre',
        'strong',
        'ul',
      ],
      ALLOWED_ATTR: [
        'aria-disabled',
        'aria-label',
        'class',
        'data-moves',
        'data-square',
        'data-uci',
        'href',
        'rel',
        'role',
        'target',
        'title',
      ],
    });

    return tokens.reduce(
      (value, token) => value.replaceAll(token.marker, this.renderReference(token.reference)),
      sanitized,
    );
  }

  private buildTokens(text: string): CoachReferenceToken[] {
    const tokens: CoachReferenceToken[] = [];
    const expression = /\[\[([a-z]+):([^\[\]]*)\]\]/gi;
    let match: RegExpExecArray | null;
    while ((match = expression.exec(text)) !== null) {
      const reference = parseCoachReference(match[1], match[2]);
      if (reference) {
        tokens.push({
          marker: `COACH_REFERENCE_TOKEN_${tokens.length}_END`,
          source: match[0],
          reference,
        });
      }
    }
    return tokens;
  }

  private renderReference(reference: CoachReference): string {
    if (reference.kind === 'move') {
      const uci = this.escapeAttribute(reference.uci);
      const label = this.escapeHtml(reference.label);
      const ariaLabel = this.escapeAttribute(reference.label);
      if (!this.isLegalMove(reference.uci)) {
        return `<span class="coach-reference coach-move-disabled" aria-disabled="true" title="Coup indisponible pour le trait actuel">${label}</span>`;
      }
      return `<a href="#chess-${uci}" role="button" class="coach-reference coach-move" data-uci="${uci}" aria-label="Jouer le coup ${ariaLabel}">${label}</a>`;
    }

    if (reference.kind === 'square') {
      const square = this.escapeAttribute(reference.square);
      return `<a href="#chess-square-${square}" role="button" class="coach-reference coach-square-reference" data-square="${square}" aria-label="Surligner la case ${square}">${this.escapeHtml(reference.label)}</a>`;
    }

    const moves = reference.moves.join(',');
    const encodedMoves = this.escapeAttribute(moves);
    const label = this.escapeHtml(reference.label);
    const ariaLabel = this.escapeAttribute(reference.label);
    if (!this.isLegalLine(reference.moves)) {
      return `<span class="coach-reference coach-line-disabled" aria-disabled="true" title="Suite indisponible pour la position actuelle">${label}</span>`;
    }
    return `<a href="#chess-line-${encodedMoves}" role="button" class="coach-reference coach-line" data-moves="${encodedMoves}" aria-label="Jouer la suite ${ariaLabel}">${label}</a>`;
  }

  private previewFromTarget(link: HTMLAnchorElement | null): void {
    const move = link ? this.moveFromTarget(link) : null;
    if (move) {
      this.squarePreview.emit(null);
      this.movePreview.emit(move);
      return;
    }

    const line = link ? this.lineFromTarget(link) : null;
    if (line?.length) {
      this.squarePreview.emit(null);
      this.movePreview.emit(line[0]);
      return;
    }

    const square = link ? this.squareFromTarget(link) : null;
    if (square) {
      this.movePreview.emit(null);
      this.squarePreview.emit(square);
    }
  }

  private clearPreview(link: HTMLAnchorElement): void {
    if (this.moveFromTarget(link) || this.lineFromTarget(link)) {
      this.movePreview.emit(null);
    } else if (this.squareFromTarget(link)) {
      this.squarePreview.emit(null);
    }
  }

  private moveFromTarget(link: HTMLAnchorElement): BoardMove | null {
    if (!link.classList.contains('coach-move')) {
      return null;
    }
    const uci = link.getAttribute('href')?.match(/^#chess-([a-h][1-8][a-h][1-8][qrbn]?)$/i)?.[1];
    return uci && this.isLegalMove(uci) ? this.toBoardMove(uci) : null;
  }

  private lineFromTarget(link: HTMLAnchorElement): BoardMove[] | null {
    if (!link.classList.contains('coach-line')) {
      return null;
    }
    const moves = link.getAttribute('href')?.match(/^#chess-line-([a-h][1-8][a-h][1-8][qrbn]?(?:,[a-h][1-8][a-h][1-8][qrbn]?)+)$/i)?.[1]?.split(',') ?? [];
    return this.isLegalLine(moves) ? moves.map((uci) => this.toBoardMove(uci)).filter((move): move is BoardMove => !!move) : null;
  }

  private squareFromTarget(link: HTMLAnchorElement): string | null {
    return link.classList.contains('coach-square-reference')
      ? link.getAttribute('href')?.match(/^#chess-square-([a-h][1-8])$/i)?.[1] ?? null
      : null;
  }

  private referenceLink(target: EventTarget | null): HTMLAnchorElement | null {
    if (!(target instanceof Element)) {
      return null;
    }
    return target.closest<HTMLAnchorElement>('.coach-reference');
  }

  private isInsideLink(target: EventTarget | null, link: HTMLAnchorElement | null): boolean {
    return target instanceof Node && link?.contains(target) === true;
  }

  private isLegalMove(uci: string): boolean {
    return this.legalMoves().includes(uci.toLowerCase());
  }

  private isLegalLine(moves: string[]): boolean {
    if (!moves.length || !this.fen()) {
      return false;
    }
    try {
      const chess = new Chess(this.fen());
      for (const uci of moves) {
        const move = this.toBoardMove(uci);
        if (!move) {
          return false;
        }
        chess.move({ ...move, promotion: move.promotion ?? 'q' });
      }
      return true;
    } catch {
      return false;
    }
  }

  private toBoardMove(uci: string): BoardMove | null {
    if (!/^[a-h][1-8][a-h][1-8][qrbn]?$/i.test(uci)) {
      return null;
    }
    const promotion = uci.length === 5 ? (uci[4].toLowerCase() as BoardMove['promotion']) : undefined;
    return { from: uci.slice(0, 2), to: uci.slice(2, 4), ...(promotion ? { promotion } : {}) };
  }

  private escapeHtml(value: string): string {
    return value
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;');
  }

  private escapeAttribute(value: string): string {
    return this.escapeHtml(value).replaceAll('"', '&quot;');
  }
}
