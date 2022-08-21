# Plotting and graphing related utilities #

from object_database.web.cells.webgl_plot import Plot


def bar_plot(x_coords, y_coords, width, color):
    """
    I return a Plot() object with bars (created out of stacked triangles).
    Parameters
    ----------
    x_coords : array
    y_coords: array
    width: float
    color: string
    """
    plot = Plot()
    for x, y in zip(x_coords, y_coords):
        plot = plot.withTriangles(
            [x, x, x + width],
            [0, y, y],
            [color, color, color]
        )
        plot = plot.withTriangles(
            [x, x + width, x + width],
            [0, y, 0],
            [color, color, color]
        )

    return plot
