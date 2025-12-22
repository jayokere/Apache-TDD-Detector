from db import (
    get_all_mined_project_names,
    get_java_projects_to_mine,
    get_python_projects_to_mine,
    get_cpp_projects_to_mine
)

def main():
    print("Connecting to database and calculating quotas...\n")
    
    # 1. Get the set of names for projects that have ACTUAL data mined
    # This queries the 'mined-commits-temp' collection
    already_mined_names = get_all_mined_project_names()
    
    # 2. Get the full lists of candidate projects from 'mined-repos'
    java_candidates = get_java_projects_to_mine()
    python_candidates = get_python_projects_to_mine()
    cpp_candidates = get_cpp_projects_to_mine()
    
    # 3. Helper function to count intersections
    def get_counts(candidates, mined_set):
        mined_count = 0
        for project in candidates:
            if project['name'] in mined_set:
                mined_count += 1
        return mined_count, len(candidates)

    # 4. Calculate stats
    j_mined, j_total = get_counts(java_candidates, already_mined_names)
    p_mined, p_total = get_counts(python_candidates, already_mined_names)
    c_mined, c_total = get_counts(cpp_candidates, already_mined_names)
    
    total_mined = j_mined + p_mined + c_mined
    total_avail = j_total + p_total + c_total

    # 5. Print Table
    print(f"{'LANGUAGE':<10} | {'MINED':<10} | {'AVAILABLE':<10} | {'STATUS'}")
    print("-" * 55)
    print(f"{'Java':<10} | {j_mined:<10} | {j_total:<10} | {j_mined/60*100:.1f}% of Target (60)")
    print(f"{'Python':<10} | {p_mined:<10} | {p_total:<10} | {p_mined/60*100:.1f}% of Target (60)")
    print(f"{'C++':<10} | {c_mined:<10} | {c_total:<10} | {c_mined/60*100:.1f}% of Target (60)")
    print("-" * 55)
    print(f"{'TOTAL':<10} | {total_mined:<10} | {total_avail:<10} |")

if __name__ == "__main__":
    main()