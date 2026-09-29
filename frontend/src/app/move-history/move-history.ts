import { Component, input } from '@angular/core';

@Component({
  selector: 'app-move-history',
  templateUrl: './move-history.html',
  styleUrl: './move-history.css',
})
export class MoveHistoryComponent {
  readonly moves = input.required<string[]>();
  readonly fen = input.required<string>();
  readonly pgn = input.required<string>();
}
