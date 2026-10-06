import {
  afterNextRender,
  Component,
  effect,
  ElementRef,
  EventEmitter,
  input,
  OnDestroy,
  Output,
  viewChild,
} from '@angular/core';
import { Chessground } from '@lichess-org/chessground';
import type { Api } from '@lichess-org/chessground/api';
import type { DrawShape } from '@lichess-org/chessground/draw';
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
  readonly arrow = input<BoardMove | null>(null);
  readonly square = input<string | null>(null);

  @Output() readonly moveRequested = new EventEmitter<BoardMove>();

  private readonly host = viewChild.required<ElementRef<HTMLElement>>('board');
  private board?: Api;

  constructor() {
    effect(() => {
      const shapes = this.currentShapes();
      this.board?.setShapes(shapes);
    });

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
        drawable: {
          enabled: false,
          visible: true,
          shapes: this.currentShapes(),
        },
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

  private currentShapes(): DrawShape[] {
    const shapes: DrawShape[] = [];
    const move = this.arrow();
    const square = this.square();
    if (move) {
      shapes.push(...this.arrowShape(move));
    }
    if (square) {
      shapes.push({ orig: square as Key, brush: 'yellow' });
    }
    return shapes;
  }

  private arrowShape(move = this.arrow()): DrawShape[] {
    if (!move) {
      return [];
    }

    return [{
      orig: move.from as Key,
      dest: move.to as Key,
      brush: 'green',
    }];
  }

  ngOnDestroy(): void {
    this.board?.destroy();
  }
}
