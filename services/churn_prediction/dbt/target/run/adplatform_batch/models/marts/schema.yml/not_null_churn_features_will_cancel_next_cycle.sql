select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select will_cancel_next_cycle
from "warehouse"."main"."churn_features"
where will_cancel_next_cycle is null



      
    ) dbt_internal_test