from collections import Counter

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import Column, hstack, vstack


def remove_duplicates(table, ra_col="ra", dec_col="dec",
                      radius=0.4*u.arcsec, sort_col=None, reverse=False,
                      flag_name="flag_cleaned"):
    """Remove duplicates from a catalogue

    This function remove duplicated sources in a catalogue. The duplicated
    sources are remove by crossmatching the table with itself and keeping the
    first source in each match.  The source kept is the first in the table but
    column names can be given to sort the table prior to removing the
    duplicates.

    Note that the duplicate removing percolates.  If A is close enough to B and
    B close enough to C, B and C will be removed, even if A is far enough from
    B.

    A flag column is added to the table containing True for sources that where
    associated to other ones during the cleaning.

    Parameters
    ----------
    table: astropy.table.Table
        The catalogue to remove duplicates from.
    ra_col: string
        Name of the right ascension column. This column must contain decimal
        degrees.
    dec_col: string
        Name of the declination column. This column must contain decimal
        degrees.
    radius: astropy quantity (distance)
        Radius for considering sources as duplicates.
    sort_col: list of strings
        If given, the catalogue will be sorted by these columns (ascending)
        before removing the duplicates. Only the first row will be taken.
    reverse: boolean
        If true, the sorted table will also be reversed.
    flag_name: string
        Name of the column containing the duplication flag to add to the
        catalogue.

    Returns
    -------
    astropy.table.Table
        A new table with the duplicated sources removed and the flag column
        added.

    """
    table = table.copy()

    if sort_col is not None:
        table.sort(sort_col)

    if reverse:
        table.reverse()

    # Position must be given in degrees
    table[ra_col].unit = u.deg
    table[dec_col].unit = u.deg

    coords = SkyCoord(table[ra_col], table[dec_col])
    idx1, idx2, _, _ = coords.search_around_sky(coords, radius)

    # We remove the association of each source to itself
    mask = (idx1 != idx2)
    idx1 = idx1[mask]
    idx2 = idx2[mask]

    # The remaining indexes are those of duplicated sources (note that idx1 ans
    # idx2 contain the same indexes in a different order). We use them to add
    # flag the sources that have duplicates.
    # We set the fill_value of this column to False so that when we stack some
    # table with astropy, the missing data will be filled with False.
    table.add_column(Column(
        name=flag_name,
        data=np.zeros(len(table)),
        dtype=bool
    ))
    table[flag_name].fill_value = False
    table[flag_name][np.unique(idx1)] = True

    # As we sorted the table (if we don't sort, it does not matter) the lower
    # indexes are the most important. We can look at the idx1 list and remove
    # all the sources that are associated to another source with a lower index.
    remove_idx = idx1[idx1 > idx2]
    keep_idx = np.in1d(np.arange(len(table)), remove_idx, invert=True)

    return table[keep_idx]


def merge_catalogues(cat_1, cat_2, racol_2, decol_2, radius=0.4*u.arcsec):
    """Merge two catalogues

    This function merges the second catalogue into the first one using the
    given radius to associate identical sources.  This function takes care to
    associate only one source of one catalogue to the other.  The sources that
    may be associated to various counterparts in the other catalogue are
    flagged as “maybe spurious association” with a true value in the
    flag_merged column.  If this column is present in the first catalogue, it's
    content is “inherited” during the merge.

    Parameters
    ----------
    cat_1: astropy.table.Table
        The table containing the first catalogue.  This is the master catalogue
        used during the merge.  If it has a “flag_merged” column it's content
        will be re-used in the flagging of the spurious merges.  This catalogue
        must contain a ‘ra’ and a ‘dec’ columns with the position in decimal
        degrees.
    cat_2: astropy.table.Table
        The table containing the second catalogue.
    racol_2: string
        Name of the column in the second table containing the right ascension
        in decimal degrees.
    decol_2: string
        Name of the column in the second table containing the declination in
        decimal degrees.
    radius: astropy.units.quantity.Quantity
        The radius to associate identical sources in the two catalogues.

    Returns
    -------
    astropy.table.Table
        The merged catalogue.

    """
    cat_1['ra'].unit = u.deg
    cat_1['dec'].unit = u.deg
    coords_1 = SkyCoord(cat_1['ra'], cat_1['dec'])

    cat_2[racol_2].unit = u.deg
    cat_2[decol_2].unit = u.deg
    coords_2 = SkyCoord(cat_2[racol_2], cat_2[decol_2])

    # Search for sources in second catalogue matching the sources in the first
    # one.
    idx_2, idx_1, d2d, _ = coords_1.search_around_sky(coords_2, radius)

    # We want to flag the possible mis-associations, i.e. the sources in each
    # catalogue that are associated to several sources in the other one, but
    # also all the sources that are associated to a problematic source in the
    # other catalogue (e.g. if two sources in the first catalogue are
    # associated to the same source in the second catalogue, they must be
    # flagged as potentially problematic).
    #
    # Search for duplicate associations
    toflag_idx_1 = np.unique([item for item, count in Counter(idx_1).items()
                              if count > 1])
    toflag_idx_2 = np.unique([item for item, count in Counter(idx_2).items()
                              if count > 1])
    # Flagging the sources associated to duplicates
    dup_associated_in_idx1 = np.in1d(idx_2, toflag_idx_2)
    dup_associated_in_idx2 = np.in1d(idx_1, toflag_idx_1)
    toflag_idx_1 = np.unique(np.concatenate(
        (toflag_idx_1, idx_1[dup_associated_in_idx1])
    ))
    toflag_idx_2 = np.unique(np.concatenate(
        (toflag_idx_2, idx_2[dup_associated_in_idx2])
    ))

    # Adding the flags to the catalogue.  In the second catalogue, the column
    # is named "flag_merged_2" and will be combined to the flag_merged column
    # one the merge is done.
    try:
        cat_1["flag_merged"] |= np.in1d(np.arange(len(cat_1), dtype=int),
                                        toflag_idx_1)
    except KeyError:
        cat_1.add_column(Column(
            data=np.in1d(np.arange(len(cat_1), dtype=int), toflag_idx_1),
            name="flag_merged"
        ))
    cat_2.add_column(Column(
        data=np.in1d(np.arange(len(cat_2), dtype=int), toflag_idx_2),
        name="flag_merged_2"
    ))

    # Now that we have flagged the maybe spurious associations, we want to
    # associate each source of each catalogue to at most one source in the
    # other one.

    # We sort the indices by the distance to take the nearest counterparts in
    # the following steps.
    sort_idx = np.argsort(d2d)
    idx_1 = idx_1[sort_idx]
    idx_2 = idx_2[sort_idx]

    # These array will contain the indexes of the matching sources in both
    # catalogues.
    match_idx_1 = np.array([], dtype=int)
    match_idx_2 = np.array([], dtype=int)

    while len(idx_1) > 0:

        both_first_idx = np.sort(np.intersect1d(
            np.unique(idx_1, return_index=True)[1],
            np.unique(idx_2, return_index=True)[1],
        ))

        new_match_idx_1 = idx_1[both_first_idx]
        new_match_idx_2 = idx_2[both_first_idx]

        match_idx_1 = np.concatenate((match_idx_1, new_match_idx_1))
        match_idx_2 = np.concatenate((match_idx_2, new_match_idx_2))

        # We remove the matching sources in both catalogues.
        to_remove = (np.in1d(idx_1, new_match_idx_1) |
                     np.in1d(idx_2, new_match_idx_2))
        idx_1 = idx_1[~to_remove]
        idx_2 = idx_2[~to_remove]

    # Indices of un-associated object in both catalogues.
    unmatched_idx_1 = np.delete(np.arange(len(cat_1), dtype=int),match_idx_1)
    unmatched_idx_2 = np.delete(np.arange(len(cat_2), dtype=int),match_idx_2)

    # Sources only in cat_1
    only_in_cat_1 = cat_1[unmatched_idx_1]

    # Sources only in cat_2
    only_in_cat_2 = cat_2[unmatched_idx_2]
    # We are using the ra and dec columns from cat_2 for the position.
    only_in_cat_2[racol_2].name = "ra"
    only_in_cat_2[decol_2].name = "dec"

    # Merged table of sources in both catalogues.
    both_in_cat_1_and_cat_2 = hstack([cat_1[match_idx_1], cat_2[match_idx_2]])
    # We don't need the positions from the second catalogue anymore.
    both_in_cat_1_and_cat_2.remove_columns([racol_2, decol_2])

    merged_catalogue = vstack([only_in_cat_1, both_in_cat_1_and_cat_2,
                               only_in_cat_2])

    # When vertically stacking the catalogues, some values in the flag columns
    # are masked because they did not exist in the catalogue some row originate
    # from. We must set them to the appropriate value.
    for colname in merged_catalogue.colnames:
        if 'flag' in colname:
            merged_catalogue[colname][merged_catalogue[colname].mask] = False

    # We combined the flag_merged flags
    merged_catalogue['flag_merged'] |= merged_catalogue['flag_merged_2']
    merged_catalogue.remove_column('flag_merged_2')

    return merged_catalogue
