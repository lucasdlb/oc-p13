import {
  afterNextRender,
  Component,
  ElementRef,
  EventEmitter,
  input,
  OnDestroy,
  Output,
  viewChild,
} from '@angular/core';
import { Chessground } from '@lichess-org/chessground';
import type { Api } from '@lichess-org/chessground/api';
import type { Dests, Key } from '@lichess-org/chessground/types';

import { BoardMove } from '../models/game';

@Component({
  selector: 'app-chessboard',
  templateUrl: './chessboard.html',
  styleUrl: './chessboard.css',
})
export class ChessboardComponent implements OnDestroy {
  readonly fen = input.required<string>();
  readonly dests = input.required<Dests>();

  @Output() readonly moveRequested = new EventEmitter<BoardMove>();

  private readonly host = viewChild.required<ElementRef<HTMLElement>>('board');
  private board?: Api;

  constructor() {
    afterNextRender(() => {
      this.board = Chessground(this.host().nativeElement, {
        fen: this.fen(),
        coordinates: true,
        movable: {
          free: false,
          color: 'white',
          dests: this.dests(),
          showDests: true,
          events: {
            after: (from: Key, to: Key) => {
              this.moveRequested.emit({ from, to });
            },
          },
        },
        premovable: { enabled: false },
        draggable: { showGhost: true },
        highlight: { lastMove: true, check: true },
      });
    });
  }

  setPosition(fen: string, turn: 'white' | 'black', dests: Dests): void {
    this.board?.set({
      fen,
      turnColor: turn,
      movable: { color: turn, dests },
    });
  }

  ngOnDestroy(): void {
    this.board?.destroy();
  }
}
