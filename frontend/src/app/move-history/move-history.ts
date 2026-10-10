import { Component, input, output, signal } from '@angular/core';

@Component({
  selector: 'app-move-history',
  templateUrl: './move-history.html',
  styleUrl: './move-history.css',
})
export class MoveHistoryComponent {
  readonly moves = input.required<string[]>();
  readonly fen = input.required<string>();
  readonly pgn = input.required<string>();
  readonly currentIndex = input.required<number>();
  readonly totalMoves = input.required<number>();

  readonly goBack = output<void>();
  readonly goForward = output<void>();
  readonly copied = signal(false);

  async copyPgn(): Promise<void> {
    const value = this.pgn() || 'Position initiale';
    await navigator.clipboard?.writeText(value);
    this.copied.set(true);
    setTimeout(() => this.copied.set(false), 1600);
  }
}
