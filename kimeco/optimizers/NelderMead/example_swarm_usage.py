"""Example usage of NelderMeadSwarm for parallel Nelder-Mead optimizations.

This example demonstrates how to use the NelderMeadSwarm class to run
multiple Nelder-Mead optimizations in parallel, each starting from a
different initial element.
"""

from optimizers.NelderMead.nelder_mead_swarm import NelderMeadSwarm
from kimeco.element import Element
from kimeco._kimeco import KiMecO
import logging

def run_nelder_mead_swarm_example():
    """Example of running NelderMeadSwarm.
    
    This assumes you have already:
    1. Created a KiMecO instance (kmo)
    2. Have a list of initial elements to optimize from
    """
    
    # Example setup (adjust paths and parameters as needed)
    input_file = 'input.json'
    workdir = '/path/to/your/workdir'
    
    # Initialize KiMecO
    kmo = KiMecO(
        input_file=input_file,
        init_loc=workdir,
        name='swarm_example'
    )
    kmo.initialize_workdir()
    kmo.copy_necessary_files()
    kmo.initialize_databases()
    kmo.set_scoring_function()
    kmo.set_perturbator()
    kmo.set_important_parameters()
    
    # Get or create initial elements
    # Option 1: Load from existing generation
    from kimeco.goat import GOATs
    goats = GOATs.from_file(
        filename=f'{workdir}/goats.txt',
        sop_db=kmo.sop_db,
        kin_db=kmo.kin_db,
        sim_db=kmo.sim_db
    )
    initial_elements = goats.get_goat_for_gen(-1)  # Get last generation
    
    # Option 2: Create from perturbation
    # from kimeco.generation import Generation
    # gen = Generation(
    #     elements=[...],  # Your elements
    #     settings=kmo.settings,
    #     rc_tpl=kmo.rc_tpl,
    #     sop_db=kmo.sop_db,
    #     kin_db=kmo.kin_db,
    #     sim_db=kmo.sim_db,
    #     sf=kmo.sf,
    #     pert=kmo.pert,
    #     klog=kmo.klog
    # )
    # initial_elements = gen.elements
    
    # Create and run the swarm
    swarm = NelderMeadSwarm(
        initial_elements=initial_elements[:5],  # Take first 5 for example
        settings=kmo.settings,
        sf=kmo.sf,
        pert=kmo.pert,
        sop_db=kmo.sop_db,
        sim_db=kmo.sim_db,
        kin_db=kmo.kin_db,
        input_tpl=kmo.rc_tpl,
        klog=kmo.klog
    )
    
    print(f"Starting swarm with {len(swarm.initial_elements)} NM instances")
    print(f"Optimizing parameters: {swarm.dimensions}")
    
    # Run the swarm (this will take time)
    best_elements = swarm.run()
    
    print(f"\nSwarm completed!")
    print(f"Successful optimizations: {len(best_elements)}/{len(swarm.initial_elements)}")
    
    # Access results
    for result in swarm.results:
        nm_id = result['nm_id']
        if result['success']:
            print(f"NM{nm_id:04d}: Success - {result['iterations']} iterations")
            print(f"  Best score: {result['best_element'].score:.4f}")
        else:
            print(f"NM{nm_id:04d}: Failed - {result['error']}")
    
    # The unified GOAT file is at:
    goat_file = f"{swarm.swarm_dir}/swarm_goats.txt"
    print(f"\nUnified GOAT file written to: {goat_file}")
    
    # Access individual NM results
    for nm_id in range(len(swarm.initial_elements)):
        nm_elements = swarm.registry.get_nm_elements(nm_id)
        print(f"NM{nm_id:04d}: Evaluated {len(nm_elements)} elements")
        
        # Check the NM-specific tables in databases
        table_name = f'NM{nm_id:04d}'
        if kmo.sop_db.table_exists(table_name):
            print(f"  SOP table {table_name} exists")
        if kmo.kin_db.table_exists(table_name):
            print(f"  KIN table {table_name} exists")
        if kmo.sim_db.table_exists(table_name):
            print(f"  SIM table {table_name} exists")
    
    return swarm, best_elements


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run example
    swarm, best_elements = run_nelder_mead_swarm_example()
    
    print("\nExample completed successfully!")
