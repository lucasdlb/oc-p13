import { Component, inject, signal, viewChild } from '@angular/core';
import type { Dests } from '@lichess-org/chessground/types';

import { AnalysisPanelComponent } from './analysis-panel/analysis-panel';
import { ChessboardComponent } from './chessboard/chessboard';
import { LevelSelectorComponent } from './level-selector/level-selector';
import { AnalyzePositionResponse, PedagogicalLevel } from './models/analysis';
import { BoardMove } from './models/game';
import { MoveHistoryComponent } from './move-history/move-history';
import { AnalysisService } from './services/analysis';
import { GameSnapshot, GameStateService } from './services/game-state';

@Component({
  selector: 'app-root',
  imports: [
    AnalysisPanelComponent,
    ChessboardComponent,
    LevelSelectorComponent,
    MoveHistoryComponent,
  ],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  private readonly analysisService = inject(AnalysisService);
  private readonly gameState = inject(GameStateService);
  private readonly board = viewChild(ChessboardComponent);
  private readonly initialGameState = this.gameState.snapshot();

  readonly level = signal<PedagogicalLevel>('debutant');
  readonly fen = signal(this.initialGameState.fen);
  readonly legalDests = signal<Dests>(this.initialGameState.legalDests);
  readonly pgn = signal('');
  readonly moves = signal<string[]>([]);
  readonly analysis = signal<AnalyzePositionResponse | null>(null);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);

  setLevel(level: PedagogicalLevel): void {
    this.level.set(level);
    if (this.moves().length) {
      this.analyze();
    }
  }

  reset(): void {
    this.syncGameState(this.gameState.reset());
    this.analysis.set(null);
    this.error.set(null);
  }

  playDemoMove(): void {
    this.reset();
    this.applyMove({ from: 'e2', to: 'e4' });
  }

  onMoveRequested(move: BoardMove): void {
    this.applyMove(move);
  }

  private applyMove(move: BoardMove): void {
    const result = this.gameState.applyMove(move);

    this.syncGameState(result.snapshot);

    if (result.ok) {
      this.analyze();
      return;
    }

    this.error.set('Coup illegal pour la position courante.');
  }

  private analyze(): void {
    this.loading.set(true);
    this.error.set(null);

    this.analysisService
      .analyzePosition({
        fen: this.fen(),
        pgn: this.pgn() || 'Position initiale',
        moves: this.moves(),
        level: this.level(),
      })
      .subscribe({
        next: (analysis) => {
          this.analysis.set(analysis);
          this.loading.set(false);
        },
        error: () => {
          this.error.set('Analyse indisponible. Verifie que le backend FastAPI est lance.');
          this.loading.set(false);
        },
      });
  }

  private syncGameState(state: GameSnapshot): void {
    this.fen.set(state.fen);
    this.legalDests.set(state.legalDests);
    this.pgn.set(state.pgn);
    this.moves.set(state.moves);
    this.syncBoardPosition(state);
  }

  private syncBoardPosition(state: GameSnapshot): void {
    this.board()?.setPosition(
      state.fen,
      state.turn,
      state.legalDests,
    );
  }
}
