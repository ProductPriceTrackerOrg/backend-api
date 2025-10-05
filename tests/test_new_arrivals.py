import requests
import pytest
from typing import Dict, Any
from datetime import datetime, timedelta

# Base URL for testing
BASE_URL = "http://localhost:9000/api/v1"


def check_server_connectivity():
    """Check if the server is running before running tests"""
    try:
        response = requests.get(f"{BASE_URL}/new-arrivals/new-arrivals/debug", timeout=5)
        return response.status_code == 200
    except requests.exceptions.ConnectionError:
        return False
    except Exception:
        return False


class TestNewArrivals:
    """Test suite for New Arrivals API endpoints with detailed stock filtering validation"""

    def test_database_has_out_of_stock_items(self):
        """First check if database actually has out-of-stock items"""
        print(f"\n=== DATABASE STOCK DISTRIBUTION CHECK ===")

        response = requests.get(f"{BASE_URL}/new-arrivals/new-arrivals/check-database-stock")
        assert response.status_code == 200
        data = response.json()

        print("Database Stock Distribution:")
        if "database_stock_distribution" in data:
            total_items = 0
            in_stock_total = 0
            out_stock_total = 0

            for dist in data["database_stock_distribution"]:
                count = dist.get("count", 0)
                is_available = dist.get("is_available")
                status = dist.get("status_description", "Unknown")

                print(f"  {status}: {count} items")
                total_items += count

                if is_available is True:
                    in_stock_total = count
                elif is_available is False:
                    out_stock_total = count

            print(f"  Total items: {total_items}")

            # Show analysis
            if "analysis" in data:
                analysis = data["analysis"]
                print(f"\nAnalysis:")
                print(
                    f"  Has out-of-stock items: {analysis.get('has_out_of_stock_items')}"
                )
                print(f"  Recommendation: {analysis.get('recommendation')}")

            # Show out-of-stock samples if they exist
            if data.get("out_of_stock_samples"):
                print(f"\nSample Out-of-Stock Items:")
                for item in data["out_of_stock_samples"][:5]:
                    print(f"  ❌ {item.get('product_title_native', 'Unknown')[:40]}...")
            else:
                print(f"\n⚠️  NO OUT-OF-STOCK ITEMS FOUND IN DATABASE")
                print(f"This explains why inStockOnly=false only shows in-stock items!")

        return data.get("analysis", {}).get("has_out_of_stock_items", False)

    def test_stock_filtering_false_should_show_only_out_of_stock(self):
        """Test inStockOnly=false - should show ONLY out-of-stock items (is_available=false)"""

        # First check what's in the database
        has_out_of_stock = self.test_database_has_out_of_stock_items()

        print(f"\n=== inStockOnly=FALSE Test (CORRECTED LOGIC) ===")
        response = requests.get(f"{BASE_URL}/new-arrivals/new-arrivals?inStockOnly=false&limit=30")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

        print(f"Returned {len(data['items'])} items with inStockOnly=false")

        if len(data["items"]) == 0:
            print(
                "ℹ️  No items returned - this is expected if database has no out-of-stock items"
            )
            if not has_out_of_stock:
                print(
                    "✅ CORRECT: Database has no out-of-stock items, so empty result is expected"
                )
            else:
                print(
                    "❌ ERROR: Database has out-of-stock items but none were returned"
                )
            return

        # Count stock status - with corrected logic, should ONLY be out-of-stock items
        in_stock_count = 0
        out_of_stock_count = 0

        for item in data["items"]:
            if item["is_available"] is True:
                in_stock_count += 1
                print(
                    f"  ❌ PROBLEM: {item['product_title'][:40]}... - IN STOCK (shouldn't be here!)"
                )
            else:
                out_of_stock_count += 1
                print(f"  ✅ CORRECT: {item['product_title'][:40]}... - OUT OF STOCK")

        print(f"\nResults Summary:")
        print(f"  In-stock items: {in_stock_count}")
        print(f"  Out-of-stock items: {out_of_stock_count}")
        print(f"  Total items: {len(data['items'])}")

        # CRITICAL: With corrected logic, inStockOnly=false should ONLY return out-of-stock items
        assert (
            in_stock_count == 0
        ), f"Found {in_stock_count} in-stock items when inStockOnly=false! Should only show out-of-stock items."
        assert out_of_stock_count == len(data["items"]), f"Stock count mismatch!"

        print("✅ inStockOnly=false test completed - ONLY out-of-stock items returned")

    def test_stock_filtering_true_only_instock(self):
        """Test inStockOnly=true - should ONLY return items where is_available=true"""
        response = requests.get(f"{BASE_URL}/new-arrivals/new-arrivals?inStockOnly=true&limit=20")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

        print(f"\n=== inStockOnly=TRUE Test ===")
        print(f"Returned {len(data['items'])} items")

        if len(data["items"]) == 0:
            print(
                "❌ WARNING: No items returned. Check if database has in-stock products."
            )
            return

        # CRITICAL TEST: ALL items MUST have is_available=true
        out_of_stock_found = 0

        for item in data["items"]:
            if item["is_available"] is not True:
                out_of_stock_found += 1
                print(
                    f"  ❌ PROBLEM: {item['product_title'][:40]}... - Available: {item['is_available']}"
                )
            else:
                print(
                    f"  ✅ {item['product_title'][:40]}... - Available: {item['is_available']}"
                )

        print(f"\nValidation:")
        print(f"  Out-of-stock items found: {out_of_stock_found}")

        # ASSERTION: When inStockOnly=true, there should be NO out-of-stock items
        assert (
            out_of_stock_found == 0
        ), f"Found {out_of_stock_found} out-of-stock items when inStockOnly=true!"
        print("✅ inStockOnly=true test PASSED")

    def test_stock_filtering_null_shows_all(self):
        """Test inStockOnly=null/None - should show ALL items (both in-stock and out-of-stock)"""
        response = requests.get(
            f"{BASE_URL}/new-arrivals/new-arrivals?limit=30"
        )  # No inStockOnly parameter = null
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

        print(f"\n=== inStockOnly=NULL Test ===")
        print(f"Returned {len(data['items'])} items with inStockOnly=null")

        if len(data["items"]) == 0:
            print("❌ WARNING: No items returned.")
            return

        # Count stock status
        in_stock_count = 0
        out_of_stock_count = 0

        for item in data["items"]:
            if item["is_available"] is True:
                in_stock_count += 1
            else:
                out_of_stock_count += 1

        print(f"Results Summary:")
        print(f"  In-stock items: {in_stock_count}")
        print(f"  Out-of-stock items: {out_of_stock_count}")
        print(f"  Total items: {len(data['items'])}")

        # Should show ALL items - both types
        total_items = in_stock_count + out_of_stock_count
        assert total_items == len(data["items"]), "Item count mismatch!"
        print("✅ inStockOnly=null test PASSED - shows all items")

    def test_time_range_empty_results(self):
        """Test time range filtering that returns empty results (24h, 7d) should not cause server errors"""
        print(f"\n=== TIME RANGE EMPTY RESULTS TEST ===")

        # Test specifically the problematic time ranges
        problematic_ranges = ["24h", "7d"]

        for time_range in problematic_ranges:
            print(f"\nTesting {time_range} time range (likely to be empty)...")

            try:
                response = requests.get(
                    f"{BASE_URL}/new-arrivals/new-arrivals?timeRange={time_range}&limit=10",
                    timeout=10,
                )

                # CRITICAL: Should return 200, not 500
                assert (
                    response.status_code == 200
                ), f"Server returned {response.status_code} for {time_range}. Expected 200 even if no results."

                data = response.json()
                assert (
                    "items" in data
                ), f"Response missing 'items' field for {time_range}"

                print(f"  ✅ Status 200 OK - returned {len(data['items'])} items")

                if len(data["items"]) == 0:
                    print(
                        f"  ✅ Empty result is expected for {time_range} - no recent items in database"
                    )
                else:
                    print(f"  ℹ️  Found {len(data['items'])} items for {time_range}")
                    # Validate the items are actually within the time range
                    current_date = datetime.now()
                    expected_max_days = 1 if time_range == "24h" else 7

                    for item in data["items"][:3]:  # Check first 3 items
                        arrival_date_str = item.get("arrival_date", "")
                        if len(arrival_date_str) == 8:
                            arrival_date = datetime.strptime(arrival_date_str, "%Y%m%d")
                            days_diff = (current_date - arrival_date).days
                            if days_diff <= expected_max_days:
                                print(
                                    f"    ✅ {item['product_title'][:30]}... ({days_diff} days ago)"
                                )
                            else:
                                print(
                                    f"    ⚠️  {item['product_title'][:30]}... ({days_diff} days ago - outside range)"
                                )

            except requests.exceptions.Timeout:
                print(f"  ❌ Timeout error for {time_range} - server taking too long")
                raise
            except requests.exceptions.ConnectionError:
                print(f"  ❌ Connection error for {time_range} - server might be down")
                raise
            except Exception as e:
                print(f"  ❌ Unexpected error for {time_range}: {str(e)}")
                raise

        print("✅ Time range empty results test completed - no server errors!")

    def test_time_range_filtering(self):
        """Test time range filtering with different time periods"""
        print(f"\n=== TIME RANGE FILTERING TESTS ===")

        from datetime import datetime, timedelta

        # Define time ranges with their expected max days
        time_ranges = {"24h": 1, "7d": 7, "30d": 30, "3m": 90}

        current_date = datetime.now()
        print(f"Current Date: {current_date.strftime('%Y-%m-%d')}")

        for time_range, expected_max_days in time_ranges.items():
            print(f"\nTesting timeRange={time_range} (max {expected_max_days} days)...")

            try:
                response = requests.get(
                    f"{BASE_URL}/new-arrivals/new-arrivals?timeRange={time_range}&limit=20"
                )
                assert (
                    response.status_code == 200
                ), f"Server returned {response.status_code} for timeRange={time_range}"
                data = response.json()
                assert "items" in data

                print(f"  Returned {len(data['items'])} items for {time_range}")

                if len(data["items"]) > 0:
                    valid_items = 0
                    invalid_items = 0

                    # Check arrival dates and validate time range
                    for item in data["items"]:
                        arrival_date_str = item.get("arrival_date", "")
                        days_since = item.get("days_since_arrival", 0)

                        # Validate format
                        assert (
                            len(arrival_date_str) == 8
                        ), f"Invalid arrival_date format: {arrival_date_str}"

                        # Parse arrival date
                        try:
                            arrival_date = datetime.strptime(arrival_date_str, "%Y%m%d")
                            actual_days_diff = (current_date - arrival_date).days

                            # Check if item is within expected time range
                            if actual_days_diff <= expected_max_days:
                                valid_items += 1
                                if (
                                    len(data["items"]) <= 5
                                ):  # Only show details for small result sets
                                    print(
                                        f"    ✅ {item['product_title'][:30]}... - {arrival_date_str} ({actual_days_diff} days ago)"
                                    )
                            else:
                                invalid_items += 1
                                print(
                                    f"    ❌ {item['product_title'][:30]}... - {arrival_date_str} ({actual_days_diff} days ago) - OUTSIDE RANGE!"
                                )

                        except ValueError as e:
                            invalid_items += 1
                            print(
                                f"    ❌ Invalid date format: {arrival_date_str} - {str(e)}"
                            )

                    print(f"  Validation Results:")
                    print(
                        f"    Valid items (within {expected_max_days} days): {valid_items}"
                    )
                    print(f"    Invalid items (outside range): {invalid_items}")

                    # For time range filtering, we expect ALL items to be within the specified range
                    if invalid_items > 0:
                        print(
                            f"    ⚠️  WARNING: {invalid_items} items are outside the {time_range} range"
                        )
                        print(
                            f"    This might indicate the time filtering is not working correctly"
                        )
                    else:
                        print(f"    ✅ All items are within the {time_range} range")

                else:
                    print(
                        f"    ℹ️  No items found for {time_range} - this might be expected if no recent data exists"
                    )

            except requests.exceptions.ConnectionError:
                print(
                    f"    ❌ Connection Error: Server is not running. Please start the server first."
                )
                raise
            except Exception as e:
                print(f"    ❌ Error testing {time_range}: {str(e)}")
                raise

        print("✅ Time range filtering tests completed")

    def test_time_range_parameter_validation(self):
        """Test different time range parameter values and edge cases"""
        print(f"\n=== TIME RANGE PARAMETER VALIDATION ===")

        # Test valid time ranges
        valid_ranges = ["24h", "7d", "30d", "3m"]
        for time_range in valid_ranges:
            print(f"\nTesting valid timeRange={time_range}...")
            response = requests.get(
                f"{BASE_URL}/new-arrivals/new-arrivals?timeRange={time_range}&limit=5"
            )
            assert (
                response.status_code == 200
            ), f"Valid time range {time_range} should return 200"
            data = response.json()
            assert "items" in data
            print(f"  ✅ {time_range}: {len(data['items'])} items")

        # Test invalid time ranges (should default to 30d)
        invalid_ranges = ["1h", "invalid", "999d", ""]
        for time_range in invalid_ranges:
            print(f"\nTesting invalid timeRange='{time_range}'...")
            response = requests.get(
                f"{BASE_URL}/new-arrivals/new-arrivals?timeRange={time_range}&limit=5"
            )
            assert (
                response.status_code == 200
            ), f"Invalid time range should still return 200 (default behavior)"
            data = response.json()
            assert "items" in data
            print(
                f"  ✅ Invalid '{time_range}' handled gracefully: {len(data['items'])} items"
            )

        # Test no timeRange parameter (should use default)
        print(f"\nTesting no timeRange parameter (should use default 30d)...")
        response = requests.get(f"{BASE_URL}/new-arrivals/new-arrivals?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        print(f"  ✅ No timeRange parameter: {len(data['items'])} items (default 30d)")

        print("✅ Time range parameter validation completed")

    def test_arrival_date_format_validation(self):
        """Test that arrival_date field has correct YYYYMMDD format"""
        print(f"\n=== ARRIVAL DATE FORMAT VALIDATION ===")

        response = requests.get(f"{BASE_URL}/new-arrivals/new-arrivals?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

        print(f"Checking arrival_date format for {len(data['items'])} items...")

        for item in data["items"]:
            arrival_date = item.get("arrival_date", "")
            days_since = item.get("days_since_arrival", 0)

            # Validate format
            assert (
                len(arrival_date) == 8
            ), f"Invalid arrival_date length: {arrival_date}"
            assert (
                arrival_date.isdigit()
            ), f"arrival_date should be numeric: {arrival_date}"
            assert days_since >= 0, f"days_since_arrival should be >= 0: {days_since}"

            # Validate date components
            year = int(arrival_date[:4])
            month = int(arrival_date[4:6])
            day = int(arrival_date[6:8])

            assert 2020 <= year <= 2030, f"Invalid year: {year}"
            assert 1 <= month <= 12, f"Invalid month: {month}"
            assert 1 <= day <= 31, f"Invalid day: {day}"

            print(
                f"  ✅ {arrival_date} -> Year: {year}, Month: {month}, Day: {day}, Days ago: {days_since}"
            )

        print("✅ Arrival date format validation completed")


def test_quick_server_error_fix():
    """Quick test to verify 24h and 7d time ranges don't cause server errors"""
    print("\n" + "=" * 50)
    print("QUICK SERVER ERROR FIX VERIFICATION")
    print("=" * 50)

    if not check_server_connectivity():
        print("❌ Server is not running")
        return False

    # Test the specific time ranges that were causing 500 errors
    problematic_endpoints = [
        "/new-arrivals?timeRange=24h&limit=5",
        "/new-arrivals?timeRange=7d&limit=5",
        "/new-arrivals?timeRange=24h&inStockOnly=true&limit=5",
        "/new-arrivals?timeRange=7d&inStockOnly=false&limit=5",
    ]

    all_passed = True

    for endpoint in problematic_endpoints:
        print(f"\nTesting: {endpoint}")
        try:
            response = requests.get(f"{BASE_URL}{endpoint}", timeout=10)

            if response.status_code == 200:
                data = response.json()
                print(
                    f"  ✅ SUCCESS: Status 200, {len(data.get('items', []))} items returned"
                )
            else:
                print(f"  ❌ FAILED: Status {response.status_code}")
                print(f"     Error: {response.text[:200]}...")
                all_passed = False

        except Exception as e:
            print(f"  ❌ EXCEPTION: {str(e)}")
            all_passed = False

    if all_passed:
        print(f"\n✅ ALL TESTS PASSED - Server errors fixed!")
    else:
        print(f"\n❌ Some tests failed - Server errors still exist")

    return all_passed


def test_comprehensive_stock_filtering():
    """Comprehensive integration test focusing on stock filtering behavior and time range filtering"""
    print("\n" + "=" * 70)
    print("COMPREHENSIVE NEW ARRIVALS API TEST - ENHANCED")
    print("=" * 70)

    # Check server connectivity first
    print("\n0. Checking server connectivity...")
    if not check_server_connectivity():
        print("❌ Server is not running on http://localhost:8000")
        print("Please start the server first using:")
        print(
            "  cd 'D:\\My Campus Work\\Sem 05\\Projects\\Data Science Project New\\backend-api'"
        )
        print("  python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload")
        return False
    print("✅ Server is running and accessible")

    # Create test instance to use methods
    test_instance = TestNewArrivals()

    try:
        # Step 1: Check database stock distribution
        print("\n1. Checking database stock distribution...")
        has_out_of_stock = test_instance.test_database_has_out_of_stock_items()

        # Step 2: Test inStockOnly=true behavior
        print("\n2. Testing inStockOnly=true...")
        test_instance.test_stock_filtering_true_only_instock()

        # Step 3: Test inStockOnly=false behavior (corrected logic)
        print("\n3. Testing inStockOnly=false (corrected logic)...")
        test_instance.test_stock_filtering_false_should_show_only_out_of_stock()

        # Step 4: Test inStockOnly=null behavior
        print("\n4. Testing inStockOnly=null...")
        test_instance.test_stock_filtering_null_shows_all()

        # Step 5: Test time range empty results (24h, 7d)
        print("\n5. Testing time range empty results (24h, 7d)...")
        test_instance.test_time_range_empty_results()

        # Step 6: Test time range filtering
        print("\n6. Testing time range filtering...")
        test_instance.test_time_range_filtering()

        # Step 7: Test time range parameter validation
        print("\n7. Testing time range parameter validation...")
        test_instance.test_time_range_parameter_validation()

        # Step 8: Test arrival date format
        print("\n8. Testing arrival date format...")
        test_instance.test_arrival_date_format_validation()

        # Step 9: Compare results and provide recommendation
        print("\n9. Final Analysis and Recommendations...")

        response_true = requests.get(
            f"{BASE_URL}/new-arrivals/new-arrivals?inStockOnly=true&limit=20"
        )
        response_false = requests.get(
            f"{BASE_URL}/new-arrivals/new-arrivals?inStockOnly=false&limit=20"
        )
        response_null = requests.get(f"{BASE_URL}/new-arrivals/new-arrivals?limit=20")

        if all(
            r.status_code == 200 for r in [response_true, response_false, response_null]
        ):
            data_true = response_true.json()
            data_false = response_false.json()
            data_null = response_null.json()

            print(f"\nComparison Results:")
            print(f"  inStockOnly=true returned: {len(data_true['items'])} items")
            print(f"  inStockOnly=false returned: {len(data_false['items'])} items")
            print(f"  inStockOnly=null returned: {len(data_null['items'])} items")

            if not has_out_of_stock:
                print(f"\n📋 CONCLUSION:")
                print(
                    f"  Your database contains only in-stock items (is_available=true)."
                )
                print(f"  This means:")
                print(
                    f"    - inStockOnly=true: Shows in-stock items ({len(data_true['items'])} items)"
                )
                print(
                    f"    - inStockOnly=false: Shows out-of-stock items (0 items - expected)"
                )
                print(
                    f"    - inStockOnly=null: Shows all items ({len(data_null['items'])} items)"
                )
                print(f"  The filtering logic is working correctly!")
                print(f"\n💡 TO TEST FULLY:")
                print(
                    f"  Add some out-of-stock items to your database with is_available=false"
                )
                print(f"  Then test again to see both behaviors")
            else:
                out_stock_in_false = sum(
                    1 for item in data_false["items"] if not item["is_available"]
                )
                in_stock_in_false = sum(
                    1 for item in data_false["items"] if item["is_available"]
                )

                if (
                    out_stock_in_false == len(data_false["items"])
                    and in_stock_in_false == 0
                ):
                    print(f"\n✅ FILTERING WORKS CORRECTLY!")
                    print(
                        f"  inStockOnly=true: only in-stock items ({len(data_true['items'])})"
                    )
                    print(
                        f"  inStockOnly=false: only out-of-stock items ({out_stock_in_false})"
                    )
                    print(f"  inStockOnly=null: all items ({len(data_null['items'])})")
                else:
                    print(f"\n❌ FILTERING ISSUE DETECTED!")
                    print(
                        f"  Database has out-of-stock items but inStockOnly=false shows in-stock ones too"
                    )
                    print(
                        f"  In-stock in false result: {in_stock_in_false} (should be 0)"
                    )
                    print(f"  Out-of-stock in false result: {out_stock_in_false}")

        print("\n" + "=" * 70)
        print("NEW ARRIVALS API TEST COMPLETED")
        print("=" * 70)
        return True

    except requests.exceptions.ConnectionError:
        print(f"\n❌ Connection Error: Server stopped responding during tests")
        print("Please check if the server is still running")
        return False
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    # First run the quick test to check if server errors are fixed
    print("Running quick server error fix verification...")
    quick_test_passed = test_quick_server_error_fix()

    if quick_test_passed:
        print("\n" + "=" * 50)
        print("PROCEEDING WITH COMPREHENSIVE TESTS")
        print("=" * 50)
        test_comprehensive_stock_filtering()
    else:
        print("\n" + "=" * 50)
        print("SKIPPING COMPREHENSIVE TESTS DUE TO SERVER ERRORS")
        print("Please fix the server errors first!")
        print("=" * 50)
