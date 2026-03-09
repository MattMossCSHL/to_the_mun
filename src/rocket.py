"""
rocket.py — programmatic interface for constructing KSP rocket designs.

Provides the Rocket class, which builds rocket dicts through controlled
method calls. Its to_dict() output is the rocket dict format consumed by
src/structure.py's validate_rocket.

Intended usage:
    from src.rocket import Rocket
    import json

    with open("data/parts_library.json") as f:
        parts_library = json.load(f)
    parts_by_name = {p['name']: p for p in parts_library}

    r = Rocket(parts_by_name)
    r.add_part("pod_0",  "mk1-3pod",     parent=None)
    r.add_part("tank_0", "fuelTank",     parent="pod_0",  attach_node="bottom")
    r.add_part("eng_0",  "liquidEngine", parent="tank_0", attach_node="bottom")
    r.set_stage("eng_0", 0)

    r.validate(verbose=True)
"""

from src.structure import check_part_call, validate_rocket


class Rocket:
    def __init__(self, parts_library):
        """
        Initialise an empty rocket.

        Parameters
        ----------
        parts_library : dict
            Parts library keyed by internal part name, as produced by
            {p['name']: p for p in json.load(...)} over parts_library.json.
        """
        self.parts_library = parts_library
        self.parts = []
        self.stages = {}

    def __repr__(self):
        """Return a short human-readable summary of the rocket's current state."""
        return f"Rocket {len(self.parts)} parts, {len(self.stages)} staged"

    def add_part(self, id, part_type, parent, attach_node=None):
        """
        Add a part to the rocket.

        Parameters
        ----------
        id : str
            Unique identifier for this part within the rocket (e.g. 'eng_0').
        part_type : str
            Internal KSP part name (must exist in parts_library).
        parent : str or None
            Id of the parent part. None for the root part only.
        attach_node : str or None
            Name of the node on the parent part this part attaches to.
            Required for all non-root parts; omitted for the root.

        Returns
        -------
        self
            Returns self to allow optional method chaining.

        Raises
        ------
        ValueError
            If part_type is not in the parts library, id is already in use,
            or parent does not exist in the current parts list.
        """
        exists = check_part_call(part_type, self.parts_library)
        if not exists:
            raise ValueError(f"unknown part type: {part_type}")

        existing_ids = {p['id'] for p in self.parts}

        if id in existing_ids:
            raise ValueError(f"{id} already in structure")

        if parent is not None:
            if parent not in existing_ids:
                raise ValueError(f"{parent} not in structure")

        part = {'id': id, 'type': part_type, 'parent': parent}
        if attach_node is not None:
            part['attach_node'] = attach_node

        self.parts.append(part)

        return self  # leaving this in in case i want method chaining later

    def set_stage(self, part_id, stage):
        """
        Assign a stage number to a part.

        Parameters
        ----------
        part_id : str
            Id of the part to stage (must already exist in the rocket).
        stage : int
            Stage number (non-negative integer). Stage 0 fires last;
            higher numbers fire first (KSP convention).

        Returns
        -------
        self
            Returns self to allow optional method chaining.

        Raises
        ------
        ValueError
            If part_id does not exist in the rocket, or stage is not a
            non-negative integer.
        """
        existing_ids = {p['id'] for p in self.parts}
        if part_id not in existing_ids:
            raise ValueError(f'{part_id} not in structure')

        if not isinstance(stage, int) or stage < 0:
            raise ValueError('invalid stage value')

        self.stages[part_id] = stage

        return self

    def to_dict(self):
        """
        Return the rocket as a plain dict in the standard rocket dict format.

        Returns
        -------
        dict
            {'parts': [...], 'stages': {...}} — the format consumed by
            validate_rocket and all downstream pipeline components.
        """
        out_dict = {'parts': self.parts,
                    'stages': self.stages}

        return out_dict

    def validate(self, verbose=False):
        """
        Run all structural validity checks on the current rocket.

        Parameters
        ----------
        verbose : bool
            If True, prints which check failed and why before returning False.

        Returns
        -------
        bool
            True if the rocket passes all structural checks, False otherwise.
        """
        return validate_rocket(self.to_dict(), self.parts_library, verbose=verbose)
