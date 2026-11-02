declare module "delaunator" {
  export default class Delaunator<P> {
    static from<P>(points: ArrayLike<P>, getX?: (p: P) => number, getY?: (p: P) => number): Delaunator<P>;
    constructor(coords: ArrayLike<number>);
    triangles: Uint32Array;
    halfedges: Int32Array;
    hull: Uint32Array;
    coords: ArrayLike<number>;
  }
}
