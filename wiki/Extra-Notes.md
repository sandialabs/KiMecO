# Extra Notes

- Mandatory top-level keys: mess_inputs, ct_yaml, experiments.
- Exactly one of initial_ratio or initial_concentration must be set for each experiment.
- Experiment pressure units are canonicalized and converted to Pa for cantera simulation; MESS pressure grid is built in bar.
- Ensembles (generations, GOAT, Nelder-Mead Swarm) are referenced by a tag name (e.g., G0001, GT-1, etc.) and must exist in the database for postprocessing to succeed.
- Inputs can be prepared using the command `kmo_start`, which will generate a JSON file with the correct structure and chosen values. The JSON can then be edited manually or reloaded into the GUI for further editing.
- While some analysis is possible using the GUI (called with keyword `kmoui`), it is still in development, and analysis of the results is best done using Jupyter notebooks or scripts that load the database and perform postprocessing.
